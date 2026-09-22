"""Deterministic lead/account routing with explicit conflict resolution.

Order of decision:
  0. a **named account** is assigned to its owner and no rule can move it
  1. lowest `priority` number wins
  2. tie → the more specific rule (more conditions) wins
  3. tie → alphabetical rule key (stable, documented, boring on purpose)
  4. nothing matched → the **fallback queue**, which is a destination, not a shrug

Existing active owners are kept unless the winning rule is allowed to override ownership.

Pool strategies:
  `pool_least_loaded` — lowest load/capacity ratio; the right default when capacity differs.
  `round_robin`       — even distribution regardless of current load.

Every assignment carries an **SLA**: the rule's `sla_hours` becomes a due-by timestamp on the decision,
because a lead routed to the right rep and then ignored for three days was not really routed. Speed to
first touch is the metric inbound routing exists to protect.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from gtmos.domain.rules import Condition, evaluate_all


@dataclass(frozen=True)
class RuleSpec:
    key: str
    name: str
    priority: int
    conditions: tuple[Condition, ...]
    strategy: str  # user | pool_least_loaded | round_robin
    assign_user_id: str | None = None
    assign_team: str | None = None
    overrides_existing_owner: bool = False
    is_active: bool = True
    # Hours allowed between this assignment and the first outbound touch. None means no commitment,
    # which is itself a decision worth seeing on the rules page.
    sla_hours: int | None = None
    # The destination for accounts no other rule claims. Exactly one rule should carry this, and it is
    # evaluated last however its priority is set.
    is_fallback: bool = False

    @property
    def destination(self) -> str:
        return f"user:{self.assign_user_id}" if self.strategy == "user" else f"team:{self.assign_team}"


@dataclass(frozen=True)
class UserFacts:
    id: str
    name: str
    team: str | None
    is_active: bool
    capacity: int
    load: int


@dataclass
class RoutingOutcome:
    # assigned | kept_owner | named_account | fallback_queue | unmatched
    # `unmatched` now means only "no rule matched and no fallback queue is configured" — a
    # misconfiguration, not a routine outcome.
    outcome: str
    rule_key: str | None
    assigned_user_id: str | None
    matched: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)
    sla_hours: int | None = None
    sla_due_at: datetime | None = None


def _sort_key(r: RuleSpec) -> tuple[int, int, str]:
    return (r.priority, -len(r.conditions), r.key)


def _lost_because(winner: RuleSpec, loser: RuleSpec) -> str:
    if loser.priority != winner.priority:
        return f"lower priority ({loser.priority} vs {winner.priority})"
    if len(loser.conditions) != len(winner.conditions):
        return f"same priority, less specific ({len(loser.conditions)} vs {len(winner.conditions)} conditions)"
    return f"same priority and specificity; tie broken by key ('{winner.key}' < '{loser.key}')"


def pick_least_loaded(users: list[UserFacts], team: str | None) -> tuple[UserFacts | None, str]:
    pool = [u for u in users if u.team == team and u.is_active]
    if not pool:
        return None, f"No active users in team '{team}'."
    available = [u for u in pool if u.load < u.capacity]
    note = ""
    if not available:
        available = pool
        note = " All members are at capacity; assigned to the least loaded anyway (capacity alert)."
    chosen = min(available, key=lambda u: (u.load / max(u.capacity, 1), u.name, u.id))
    return chosen, (
        f"Least-loaded member of {team}: {chosen.name} ({chosen.load}/{chosen.capacity} open accounts).{note}"
    )


def pick_round_robin(users: list[UserFacts], team: str | None, unit_id: str) -> tuple[UserFacts | None, str]:
    """Even distribution across a team, chosen by hashing the account rather than by a shared counter.

    A real round robin keeps a pointer and hands out the next rep, which gives exact balance but needs a
    lock and makes the same account land on a different rep depending on when it was routed. Hashing the
    account id over a stable, sorted pool gives the same even distribution in expectation while staying
    idempotent: re-running routing after a replay or a crash reaches the same rep, and two workers racing
    cannot produce two different owners. Exact balance is the thing given up, and load-based assignment
    (`pool_least_loaded`) is the better strategy when that matters.
    """
    pool = sorted((u for u in users if u.team == team and u.is_active), key=lambda u: (u.name, u.id))
    if not pool:
        return None, f"No active users in team '{team}'."
    digest = hashlib.sha256(f"{team}:{unit_id}".encode()).hexdigest()
    chosen = pool[int(digest[:12], 16) % len(pool)]
    return chosen, (
        f"Round robin across {team} ({len(pool)} active): {chosen.name}. The account id picks the seat, "
        "so the same account always routes to the same rep."
    )


def route(
    rules: list[RuleSpec],
    ctx: dict[str, Any],
    users: list[UserFacts],
    now: datetime | None = None,
) -> RoutingOutcome:
    users_by_id = {u.id: u for u in users}
    account = ctx.get("account", {})

    def with_sla(outcome: RoutingOutcome, rule: RuleSpec | None) -> RoutingOutcome:
        if rule is not None and rule.sla_hours and outcome.assigned_user_id and now is not None:
            outcome.sla_hours = rule.sla_hours
            outcome.sla_due_at = now + timedelta(hours=rule.sla_hours)
            outcome.explanation.append(
                f"First touch is due within {rule.sla_hours}h of this assignment ({rule.name} SLA)."
            )
        return outcome

    # A named account belongs to its rep by agreement, usually one negotiated above the RevOps team.
    # Territory rules do not get a vote, and routing that quietly reassigns one is how trust in routing
    # is lost.
    if account.get("is_named_account"):
        owner_id = account.get("owner_id")
        owner = users_by_id.get(owner_id) if owner_id else None
        if owner is not None and owner.is_active:
            return RoutingOutcome(
                "named_account",
                None,
                owner.id,
                [],
                [],
                [f"{account.get('name', 'Account')} is a named account owned by {owner.name}; rules do not apply."],
            )

    candidates = [r for r in rules if r.is_active and not r.is_fallback]
    fallback = next((r for r in rules if r.is_active and r.is_fallback), None)
    matched: list[tuple[RuleSpec, list[dict[str, Any]]]] = []
    for r in sorted(candidates, key=_sort_key):
        ok, results = evaluate_all(list(r.conditions), ctx)
        if ok:
            matched.append((r, results))

    matched_view = [{"rule": r.key, "name": r.name, "priority": r.priority, "conditions": res} for r, res in matched]
    if not matched:
        if fallback is None:
            return RoutingOutcome(
                "unmatched",
                None,
                None,
                [],
                [],
                [
                    "No routing rule matched and no fallback queue is configured, so this account has "
                    "no owner. That is a gap in the rules, not a property of the account."
                ],
            )
        explanation = [
            f"No territory rule matched, so the account goes to the fallback queue ('{fallback.name}'). "
            "Unrouted accounts are worked by someone rather than disappearing."
        ]
        chosen, why = _assign_pool(fallback, users, ctx, users_by_id)
        explanation.append(why)
        if chosen is None:
            return RoutingOutcome("unmatched", fallback.key, None, matched_view, [], explanation)
        return with_sla(
            RoutingOutcome("fallback_queue", fallback.key, chosen.id, matched_view, [], explanation), fallback
        )

    winner, _ = matched[0]
    explanation = [
        f"Matched rule '{winner.name}' (priority {winner.priority}): "
        + "; ".join(c.describe() for c in winner.conditions)
    ]
    conflicts: list[dict[str, Any]] = []
    for loser, _ in matched[1:]:
        entry: dict[str, Any] = {
            "rule": loser.key,
            "name": loser.name,
            "destination": loser.destination,
            "lost_because": _lost_because(winner, loser),
        }
        if loser.destination != winner.destination:
            entry["is_conflict"] = True
            conflicts.append(entry)
            explanation.append(f"Also matched '{loser.name}' → {loser.destination}; lost: {entry['lost_because']}.")

    owner_id = account.get("owner_id")
    owner = users_by_id.get(owner_id) if owner_id else None
    if owner and owner.is_active and not winner.overrides_existing_owner:
        explanation.append(f"Kept existing owner {owner.name}: ownership is respected unless the rule overrides it.")
        return RoutingOutcome("kept_owner", winner.key, owner.id, matched_view, conflicts, explanation)
    if owner and not owner.is_active:
        explanation.append(f"Previous owner {owner.name} is inactive; reassigning.")
    elif owner and winner.overrides_existing_owner:
        explanation.append(f"Rule overrides existing owner {owner.name}.")

    if winner.strategy == "user":
        target = users_by_id.get(winner.assign_user_id or "")
        if target and target.is_active:
            explanation.append(f"Assigned directly to {target.name}.")
            return with_sla(
                RoutingOutcome("assigned", winner.key, target.id, matched_view, conflicts, explanation), winner
            )
        explanation.append("Named assignee is missing or inactive; falling back to their team's pool.")
        chosen, why = _assign_pool(winner, users, ctx, users_by_id, team=target.team if target else None)
    else:
        chosen, why = _assign_pool(winner, users, ctx, users_by_id)
    explanation.append(why)
    if chosen is None:
        # The rule matched but its destination is empty (a team with nobody active in it). That is an
        # operational problem, and saying "unmatched" would blame the account for it.
        explanation.append(
            f"Rule '{winner.name}' matched but has no one to assign to; the account is unowned until "
            "the team has an active member."
        )
        return RoutingOutcome("unmatched", winner.key, None, matched_view, conflicts, explanation)
    return with_sla(RoutingOutcome("assigned", winner.key, chosen.id, matched_view, conflicts, explanation), winner)


def _assign_pool(
    rule: RuleSpec,
    users: list[UserFacts],
    ctx: dict[str, Any],
    users_by_id: dict[str, UserFacts],
    team: str | None = None,
) -> tuple[UserFacts | None, str]:
    target_team = team if team is not None else rule.assign_team
    if rule.strategy == "user":
        direct = users_by_id.get(rule.assign_user_id or "")
        if direct and direct.is_active:
            return direct, f"Assigned directly to {direct.name}."
        target_team = direct.team if direct else target_team
    if rule.strategy == "round_robin":
        return pick_round_robin(users, target_team, str(ctx.get("account", {}).get("id", "")))
    return pick_least_loaded(users, target_team)
