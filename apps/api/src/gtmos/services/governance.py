"""Runtime kill switches.

Environment variables decide what GTMOS *can* do; these decide what it *is doing right now*. The
difference matters at 2am: `HUBSPOT_LIVE_WRITES_ENABLED` needs an engineer, a config change and a
restart, while an operator who has just watched a bad sequence start sending needs a stop button.

Three switches rather than one, because the reasons differ:

    automation   workflows stop firing            (a rule is misbehaving)
    outbound     nothing is sent or approved      (a message or list is wrong)
    crm_writes   nothing is pushed to the CRM     (sync is corrupting records)

`pause_all` turns off all three at once and records who and why, because the first question after an
incident is always "when did we stop, and who stopped us".

Every check is a database read on the workspace, not a cached flag, so a pause takes effect on the
next action rather than after a deploy or a TTL.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from gtmos.models import Workspace
from gtmos.services.common import audit, utcnow

# name -> (label, what it stops, why you would use it)
SWITCHES: dict[str, tuple[str, str, str]] = {
    "automation_enabled": (
        "Automation",
        "Workflows stop triggering and queued runs stop executing.",
        "A rule is firing on the wrong accounts, or an integration is flapping.",
    ),
    "outbound_enabled": (
        "Outbound",
        "No draft can be approved and no send is recorded.",
        "A message is wrong, a list was built badly, or deliverability is degrading.",
    ),
    "crm_writes_enabled": (
        "CRM writes",
        "Reverse ETL and the sync step stop pushing to the CRM.",
        "Sync is overwriting rep edits or writing to the wrong records.",
    ),
}


class Halted(Exception):
    """Raised when an action is attempted while its switch is off. Carries an operator-readable why."""

    def __init__(self, switch: str, reason: str | None = None) -> None:
        label = SWITCHES[switch][0]
        detail = f"{label} is paused"
        if reason:
            detail += f": {reason}"
        super().__init__(detail)
        self.switch = switch
        self.reason = reason


@dataclass
class Governance:
    automation_enabled: bool
    outbound_enabled: bool
    crm_writes_enabled: bool
    paused_at: Any = None
    paused_by: str | None = None
    paused_reason: str | None = None

    @property
    def all_paused(self) -> bool:
        return not (self.automation_enabled or self.outbound_enabled or self.crm_writes_enabled)

    def as_dict(self) -> dict[str, Any]:
        return {
            "switches": [
                {
                    "key": key,
                    "label": label,
                    "enabled": getattr(self, key),
                    "stops": stops,
                    "use_when": why,
                }
                for key, (label, stops, why) in SWITCHES.items()
            ],
            "all_paused": self.all_paused,
            "any_paused": any(not getattr(self, k) for k in SWITCHES),
            "paused_at": self.paused_at,
            "paused_by": self.paused_by,
            "paused_reason": self.paused_reason,
        }


def state(ws: Workspace) -> Governance:
    return Governance(
        automation_enabled=ws.automation_enabled,
        outbound_enabled=ws.outbound_enabled,
        crm_writes_enabled=ws.crm_writes_enabled,
        paused_at=ws.paused_at,
        paused_by=ws.paused_by,
        paused_reason=ws.paused_reason,
    )


def is_enabled(db: Session, workspace_id: uuid.UUID, switch: str) -> bool:
    """Read the switch from the database on every check.

    A cached flag would mean a pause takes effect whenever the cache happens to expire, which is the
    one property a kill switch cannot have.
    """
    ws = db.get(Workspace, workspace_id)
    return bool(getattr(ws, switch)) if ws else True


def require(db: Session, workspace_id: uuid.UUID, switch: str) -> None:
    ws = db.get(Workspace, workspace_id)
    if ws is not None and not getattr(ws, switch):
        raise Halted(switch, ws.paused_reason)


def set_switch(db: Session, ws: Workspace, switch: str, enabled: bool, actor: str, reason: str = "") -> Governance:
    if switch not in SWITCHES:
        raise ValueError(f"unknown switch: {switch}")
    before = getattr(ws, switch)
    setattr(ws, switch, enabled)
    if not enabled:
        ws.paused_at = utcnow()
        ws.paused_by = actor
        ws.paused_reason = reason or ws.paused_reason
    elif all(getattr(ws, k) for k in SWITCHES):
        ws.paused_at = None
        ws.paused_by = None
        ws.paused_reason = None
    audit(
        db,
        ws.id,
        "governance.switch_changed",
        "workspace",
        ws.id,
        before={switch: before},
        after={switch: enabled},
        reason=reason or ("resumed" if enabled else "paused"),
        actor=actor,
    )
    db.flush()
    return state(ws)


def pause_all(db: Session, ws: Workspace, actor: str, reason: str) -> Governance:
    """The stop button. One action, because an incident is not the moment to pick switches."""
    for switch in SWITCHES:
        setattr(ws, switch, False)
    ws.paused_at = utcnow()
    ws.paused_by = actor
    ws.paused_reason = reason
    audit(
        db,
        ws.id,
        "governance.paused",
        "workspace",
        ws.id,
        after=dict.fromkeys(SWITCHES, False),
        reason=reason,
        actor=actor,
    )
    db.flush()
    return state(ws)


def resume_all(db: Session, ws: Workspace, actor: str, reason: str = "") -> Governance:
    for switch in SWITCHES:
        setattr(ws, switch, True)
    ws.paused_at = None
    ws.paused_by = None
    ws.paused_reason = None
    audit(
        db,
        ws.id,
        "governance.resumed",
        "workspace",
        ws.id,
        after=dict.fromkeys(SWITCHES, True),
        reason=reason or "resumed",
        actor=actor,
    )
    db.flush()
    return state(ws)
