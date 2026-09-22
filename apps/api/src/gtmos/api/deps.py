"""Request dependencies and the demo-safe auth boundary.

V1 runs as a single operator identity (no login) so the demo is frictionless. Safety comes from what the
API refuses to do without explicit configuration:
  * Live CRM writes require HUBSPOT_LIVE_WRITES_ENABLED=true and, when ADMIN_API_TOKEN is set, a matching
    `Authorization: Bearer <token>` header.
  * Destructive/admin endpoints (bulk rescore, ICP changes, reseed) require the admin token whenever one is
    configured, and always in production.
  * Webhooks authenticate with HMAC signatures (see integrations/signatures.py).
Production would put SSO/OIDC in front of this and map users to roles; see docs/architecture.md.
"""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from gtmos.config import get_settings
from gtmos.db import get_db
from gtmos.models import Base, Workspace
from gtmos.services.common import get_workspace, jsonable


def db_session() -> Iterator[Session]:
    yield from get_db()


def workspace(db: Session = Depends(db_session)) -> Workspace:
    return get_workspace(db)


def actor(x_gtmos_actor: str | None = Header(default=None)) -> str:
    """Who is acting. The demo UI sends the demo operator; production would derive this from the session."""
    from gtmos.services.common import DEMO_ACTOR

    if x_gtmos_actor and len(x_gtmos_actor) <= 200 and "@" in x_gtmos_actor:
        return x_gtmos_actor
    return DEMO_ACTOR


def require_admin(authorization: str | None = Header(default=None)) -> None:
    s = get_settings()
    token = s.admin_api_token.get_secret_value() if s.admin_api_token else None
    if token is None:
        if s.env == "production":
            raise HTTPException(503, "ADMIN_API_TOKEN must be configured in production")
        return
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, token):
        raise HTTPException(401, "admin token required")


def require_admin_for_live_writes(authorization: str | None = Header(default=None)) -> None:
    s = get_settings()
    if s.hubspot_access_token and s.hubspot_live_writes_enabled:
        require_admin(authorization)


class Page:
    def __init__(self, page: int = Query(1, ge=1, le=10_000), page_size: int = Query(50, ge=1, le=200)) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def row(obj: Base, *, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    return {c.key: jsonable(getattr(obj, c.key)) for c in obj.__mapper__.column_attrs if c.key not in exclude}


def parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(422, "invalid id") from exc
