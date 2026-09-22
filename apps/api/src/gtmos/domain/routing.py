"""Deterministic lead/account routing with explicit conflict resolution.

Resolution order when several rules match:
  1. lowest `priority` number wins
  2. tie → the more specific rule (more conditions) wins
  3. tie → alphabetical rule key (stable, documented, boring on purpose)
Existing active owners are kept unless the winning rule is allowed to override ownership.
Pool assignment is least-loaded (load / capacity), ties broken by name then id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gtmos.domain.rules import Condition, evaluate_all


@dataclass(frozen=True)
class RuleSpec:
    key: str
    name: str
    priority: int
    conditions: tuple[Condition, ...]
    strategy: str  # user | pool_least_loaded
    assign_user_id: str | None = None
    assign_team: str | None = None
    overrides_existing_owner: bool = False
    is_active: bool = True

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
    outcome: str  # assigned | kept_owner | unmatched
    rule_key: str | None
    assigned_user_id: str | None
    matched: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)


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


def route(
    rules: list[RuleSpec],
    ctx: dict[str, Any],
    users: list[UserFacts],
) -> RoutingOutcome:
    users_by_id = {u.id: u for u in users}
    matched: list[tuple[RuleSpec, list[dict[str, Any]]]] = []
    for r in sorted((r for r in rules if r.is_active), key=_sort_key):
        ok, results = evaluate_all(list(r.conditions), ctx)
        if ok:
            matched.append((r, results))

    matched_view = [{"rule": r.key, "name": r.name, "priority": r.priority, "conditions": res} for r, res in matched]
    if not matched:
        return RoutingOutcome(
            "unmatched", None, None, [], [], ["No routing rule matched. Account goes to the RevOps triage queue."]
        )

    winner, _ = matched[0]
    explanation = [
        f"Matched rule '{winner.name}' (priority {winner.priority}): "
        + "; ".join(c.describe() for c in winner.conditions)
    ]
    conflicts: list[dict[str, Any]] = []
    for loser, _ in matched[1:]:
        entry = {
            "rule": loser.key,
            "name": loser.name,
            "destination": loser.destination,
            "lost_because": _lost_because(winner, loser),
        }
        if loser.destination != winner.destination:
            entry["is_conflict"] = True
            conflicts.append(entry)
            explanation.append(f"Also matched '{loser.name}' → {loser.destination}; lost: {entry['lost_because']}.")

    owner_id = ctx.get("account", {}).get("owner_id")
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
            return RoutingOutcome("assigned", winner.key, target.id, matched_view, conflicts, explanation)
        explanation.append("Named assignee is missing or inactive; falling back to their team's pool.")
        team = target.team if target else winner.assign_team
        chosen, why = pick_least_loaded(users, team)
    else:
        chosen, why = pick_least_loaded(users, winner.assign_team)
    explanation.append(why)
    if chosen is None:
        return RoutingOutcome("unmatched", winner.key, None, matched_view, conflicts, explanation)
    return RoutingOutcome("assigned", winner.key, chosen.id, matched_view, conflicts, explanation)
