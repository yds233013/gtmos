"""ICP definitions, explainable scores, buying signals, enrichment provenance and research."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from gtmos.models.base import Base, IdMixin, JSONType, NullableJSONType, TimestampMixin


class ICPProfile(IdMixin, TimestampMixin, Base):
    """A versioned ideal-customer-profile definition. `definition` is validated by domain.icp.ICPDefinition."""

    __tablename__ = "icp_profiles"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(default=True)
    definition: Mapped[dict[str, Any]] = mapped_column()
    created_by: Mapped[str] = mapped_column(String(200), default="system")


class ICPScore(IdMixin, Base):
    """One computed score for an account under a specific ICP version. History is retained."""

    __tablename__ = "icp_scores"
    __table_args__ = (Index("ix_icp_scores_account_current", "account_id", "is_current"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    icp_profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("icp_profiles.id", ondelete="CASCADE"))
    icp_version: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    grade: Mapped[str] = mapped_column(String(2))
    fit: Mapped[float] = mapped_column(Float)
    intent: Mapped[float] = mapped_column(Float)
    timing: Mapped[float] = mapped_column(Float)
    technical: Mapped[float] = mapped_column(Float)
    engagement: Mapped[float] = mapped_column(Float)
    # Points subtracted for disqualifying signals, as a negative number. Stored separately because it
    # is applied after the category caps, so total != fit + intent + timing + technical + engagement
    # whenever an account carries one.
    penalty: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    excluded: Mapped[bool] = mapped_column(default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    inputs_hash: Mapped[str] = mapped_column(String(64))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(String(60), default="manual")
    is_current: Mapped[bool] = mapped_column(default=True)


class ScoreComponent(IdMixin, Base):
    __tablename__ = "score_components"

    icp_score_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("icp_scores.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(20))  # fit | intent | timing | technical | engagement
    key: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(200))
    points: Mapped[float] = mapped_column(Float)
    max_points: Mapped[float] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[Any]] = mapped_column(default=list)


class SignalType(IdMixin, Base):
    __tablename__ = "signal_types"

    key: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(20))  # intent | timing | engagement | fit
    default_strength: Mapped[float] = mapped_column(Float)  # 0..1
    half_life_days: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text)


class Signal(IdMixin, Base):
    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signals_account_time", "account_id", "observed_at"),
        Index("ix_signals_workspace_time", "workspace_id", "observed_at"),
        UniqueConstraint("workspace_id", "dedupe_key"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    signal_type: Mapped[str] = mapped_column(String(60))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(80))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    confidence: Mapped[float] = mapped_column(Float)  # 0..1: how sure we are the signal is real
    strength: Mapped[float] = mapped_column(Float)  # 0..1: how much it matters for buying intent
    title: Mapped[str] = mapped_column(String(300))
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
    data_origin: Mapped[str] = mapped_column(String(10), default="demo")
    dedupe_key: Mapped[str] = mapped_column(String(200))


class EnrichmentRun(IdMixin, Base):
    __tablename__ = "enrichment_runs"
    __table_args__ = (Index("ix_enrichment_runs_entity", "entity_type", "entity_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[uuid.UUID] = mapped_column()
    status: Mapped[str] = mapped_column(String(20))  # succeeded | partial | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fields_requested: Mapped[list[Any]] = mapped_column(default=list)
    fields_filled: Mapped[list[Any]] = mapped_column(default=list)
    fields_changed: Mapped[list[Any]] = mapped_column(default=list)
    total_cost_credits: Mapped[float] = mapped_column(Float, default=0.0)
    trigger: Mapped[str] = mapped_column(String(60), default="manual")
    is_simulated: Mapped[bool] = mapped_column(default=True)


class EnrichmentAttempt(IdMixin, Base):
    """One provider call for one field inside a waterfall. Misses and errors are recorded too."""

    __tablename__ = "enrichment_attempts"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("enrichment_runs.id", ondelete="CASCADE"))
    field: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer)  # order within the field's waterfall
    outcome: Mapped[str] = mapped_column(String(20))  # hit | miss | low_confidence | error | skipped
    value: Mapped[Any] = mapped_column(JSONType, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_credits: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)


class FieldProvenance(IdMixin, Base):
    """Current provenance of a field value on an account/contact: who set it, when, how confident."""

    __tablename__ = "field_provenance"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "field"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[uuid.UUID] = mapped_column()
    field: Mapped[str] = mapped_column(String(60))
    value: Mapped[Any] = mapped_column(JSONType, nullable=True)
    source: Mapped[str] = mapped_column(String(60))  # provider key | manual | crm | seed
    confidence: Mapped[float] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    enrichment_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("enrichment_runs.id", ondelete="SET NULL"))
    is_manual_lock: Mapped[bool] = mapped_column(default=False)
    # The provider answers that lost, when they materially disagreed with the one that won. Kept so a
    # rep can see what the alternative was and why it was not taken, instead of a value that appears
    # unanimous. Shape: {"chosen_value", "chosen_provider", "others": [...], "material", "explanation"}.
    # `none_as_null` so "no conflict" is SQL NULL rather than JSON null: the data-quality rule and the
    # UI both test for absence, and JSON null is present.
    conflict: Mapped[dict[str, Any] | None] = mapped_column(NullableJSONType, nullable=True)


class ResearchReport(IdMixin, Base):
    """AI/deterministic account research. Always a draft artifact; never written to CRM as fact."""

    __tablename__ = "research_reports"
    __table_args__ = (Index("ix_research_reports_account", "account_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | reviewed | rejected
    generator: Mapped[str] = mapped_column(String(80))  # demo-deterministic | anthropic:<model>
    prompt_version: Mapped[str] = mapped_column(String(20))
    sections: Mapped[dict[str, Any]] = mapped_column()
    unsupported_claims: Mapped[list[Any]] = mapped_column(default=list)
    input_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(200), default="system")
    reviewed_by: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)


class ResearchEvidence(IdMixin, Base):
    __tablename__ = "research_evidence"

    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_reports.id", ondelete="CASCADE"))
    ref: Mapped[str] = mapped_column(String(10))  # "E1", "E2", ... cited inline by claims
    kind: Mapped[str] = mapped_column(String(30))  # signal | firmographic | technographic | activity | ...
    label: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(80))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    source_record_type: Mapped[str | None] = mapped_column(String(40))
    source_record_id: Mapped[uuid.UUID | None] = mapped_column()
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float] = mapped_column(Float)
