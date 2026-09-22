"""Signal ingestion: normalize → dedupe → persist → rescore → trigger workflows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gtmos.domain.signals import SIGNAL_TYPES, signal_dedupe_key
from gtmos.models import Account, Signal
from gtmos.services.common import audit, utcnow


class InvalidSignal(ValueError):
    pass


@dataclass
class SignalIngestResult:
    signal: Signal
    created: bool
    score_before: int | None = None
    score_after: int | None = None
    workflow_runs: list[str] | None = None


def create_signal(
    db: Session,
    account: Account,
    *,
    signal_type: str,
    observed_at: datetime,
    source: str,
    title: str,
    explanation: str,
    source_ref: str,
    confidence: float | None = None,
    strength: float | None = None,
    evidence: dict[str, Any] | None = None,
    source_url: str | None = None,
    contact_id: uuid.UUID | None = None,
    data_origin: str = "live",
) -> tuple[Signal, bool]:
    spec = SIGNAL_TYPES.get(signal_type)
    if spec is None:
        raise InvalidSignal(f"unknown signal type '{signal_type}'")
    if confidence is not None and not 0 <= confidence <= 1:
        raise InvalidSignal("confidence must be within [0, 1]")
    if strength is not None and not 0 <= strength <= 1:
        raise InvalidSignal("strength must be within [0, 1]")
    key = signal_dedupe_key(signal_type, account.domain or str(account.id), source_ref)
    existing = db.scalars(
        select(Signal).where(Signal.workspace_id == account.workspace_id, Signal.dedupe_key == key)
    ).first()
    if existing:
        return existing, False
    s = Signal(
        workspace_id=account.workspace_id,
        account_id=account.id,
        contact_id=contact_id,
        signal_type=signal_type,
        observed_at=observed_at,
        ingested_at=utcnow(),
        source=source,
        source_url=source_url,
        confidence=confidence if confidence is not None else 0.8,
        strength=strength if strength is not None else spec.default_strength,
        title=title,
        explanation=explanation,
        evidence=evidence or {},
        data_origin=data_origin,
        dedupe_key=key,
    )
    db.add(s)
    if account.last_signal_at is None or observed_at > account.last_signal_at:
        account.last_signal_at = observed_at
    db.flush()
    audit(
        db,
        account.workspace_id,
        "signal.ingested",
        "account",
        account.id,
        after={"signal_id": str(s.id), "type": signal_type, "title": title},
        reason=f"source={source}",
        actor_type="integration" if data_origin == "live" else "system",
        actor=source,
    )
    return s, True


def ingest_signal(db: Session, account: Account, *, run_workflows: bool = True, **kw: Any) -> SignalIngestResult:
    """The full pipeline for a new signal. Duplicates are acknowledged but trigger nothing."""
    from gtmos.services.scoring_service import rescore_accounts
    from gtmos.services.workflow_engine import emit_event

    before = account.icp_score
    sig, created = create_signal(db, account, **kw)
    res = SignalIngestResult(sig, created, before, before, [])
    if not created:
        return res
    outcomes = rescore_accounts(db, account.workspace_id, [account.id], trigger=f"signal:{sig.signal_type}")
    res.score_after = account.icp_score
    if run_workflows:
        runs = emit_event(
            db,
            account.workspace_id,
            "signal.created",
            str(sig.id),
            account,
            {
                "signal": {
                    "id": str(sig.id),
                    "signal_type": sig.signal_type,
                    "title": sig.title,
                    "observed_at": sig.observed_at.isoformat(),
                }
            },
        )
        if outcomes and outcomes[0].crossed_a_grade:
            runs += emit_event(
                db,
                account.workspace_id,
                "score.threshold_crossed",
                f"{sig.id}:a-grade",
                account,
                {"event": {"threshold": 80, "from": before, "to": account.icp_score}},
            )
        res.workflow_runs = [str(r.id) for r in runs]
    return res
