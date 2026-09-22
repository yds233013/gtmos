"""Cross-cutting service helpers: request context (actor, correlation id), audit logging, JSON safety."""

from __future__ import annotations

import contextvars
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gtmos.models import AuditEvent, Workspace

DEMO_ACTOR = "demo.operator@sentinel-ai.example"

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)
_actor: contextvars.ContextVar[str] = contextvars.ContextVar("actor", default=DEMO_ACTOR)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:16]


def correlation_id() -> str:
    cid = _correlation_id.get()
    if cid is None:
        cid = new_correlation_id()
        _correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str | None) -> contextvars.Token[str | None]:
    return _correlation_id.set(cid)


def reset_correlation_id(token: contextvars.Token[str | None]) -> None:
    _correlation_id.reset(token)


def current_actor() -> str:
    return _actor.get()


def set_actor(actor: str) -> contextvars.Token[str]:
    return _actor.set(actor)


def jsonable(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple | set):
        return [jsonable(x) for x in v]
    return v


def snapshot(obj: Any, fields: list[str]) -> dict[str, Any]:
    return {f: jsonable(getattr(obj, f, None)) for f in fields}


def audit(
    db: Session,
    workspace_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    actor_type: str = "user",
    actor: str | None = None,
    occurred_at: datetime | None = None,
) -> AuditEvent:
    ev = AuditEvent(
        workspace_id=workspace_id,
        actor_type=actor_type,
        actor=actor or (current_actor() if actor_type == "user" else actor_type),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=jsonable(before) if before is not None else None,
        after=jsonable(after) if after is not None else None,
        reason=reason,
        correlation_id=correlation_id(),
        occurred_at=occurred_at or utcnow(),
    )
    db.add(ev)
    return ev


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def get_workspace(db: Session) -> Workspace:
    """V1 is single-tenant: one workspace per deployment. The schema is multi-tenant ready."""
    ws = db.scalars(select(Workspace).order_by(Workspace.created_at)).first()
    if ws is None:
        raise NotFound("No workspace. Run `make seed`.")
    return ws
