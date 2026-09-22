"""Campaigns, sequences, personalized message drafts and experiments."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from gtmos.models.base import Base, IdMixin, TimestampMixin

MESSAGE_STATUSES = ("draft", "review", "approved", "ready", "rejected")


class Campaign(IdMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="active")  # draft | active | paused | completed
    hypothesis: Mapped[str] = mapped_column(Text)
    target_segment: Mapped[dict[str, Any]] = mapped_column(default=dict)
    persona: Mapped[str | None] = mapped_column(String(80))
    trigger_signal: Mapped[str | None] = mapped_column(String(60))
    channel: Mapped[str] = mapped_column(String(20), default="email")
    value_prop: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    data_origin: Mapped[str] = mapped_column(String(10), default="demo")


class Sequence(IdMixin, Base):
    __tablename__ = "sequences"

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    variant_key: Mapped[str | None] = mapped_column(String(40))


class SequenceStep(IdMixin, Base):
    __tablename__ = "sequence_steps"
    __table_args__ = (UniqueConstraint("sequence_id", "step_number"),)

    sequence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sequences.id", ondelete="CASCADE"))
    step_number: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(20))  # email | linkedin | call | task
    delay_days: Mapped[int] = mapped_column(Integer, default=0)
    subject_template: Mapped[str | None] = mapped_column(String(500))
    body_template: Mapped[str] = mapped_column(Text)


class MessageDraft(IdMixin, TimestampMixin, Base):
    """Evidence-grounded personalization. Moves DRAFT → REVIEW → APPROVED → READY. Never auto-sent."""

    __tablename__ = "message_drafts"
    __table_args__ = (Index("ix_message_drafts_status", "workspace_id", "status"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"))
    research_report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("research_reports.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(20))  # email | linkedin | call_prep
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    angle: Mapped[str] = mapped_column(String(80))
    reasoning_chain: Mapped[dict[str, Any]] = mapped_column(default=dict)  # signal→pain→value→evidence→cta
    evidence: Mapped[list[Any]] = mapped_column(default=list)
    guardrails: Mapped[list[Any]] = mapped_column(default=list)  # [{check, passed, detail}]
    status: Mapped[str] = mapped_column(String(20), default="draft")
    generator: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1)
    reviewed_by: Mapped[str | None] = mapped_column(String(200))
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column()


class Experiment(IdMixin, TimestampMixin, Base):
    __tablename__ = "experiments"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    hypothesis: Mapped[str] = mapped_column(Text)
    null_hypothesis: Mapped[str] = mapped_column(Text)
    primary_metric: Mapped[str] = mapped_column(String(40))  # reply | positive_reply | meeting | opportunity
    unit: Mapped[str] = mapped_column(String(20), default="contact")
    status: Mapped[str] = mapped_column(String(20), default="running")  # draft | running | stopped
    salt: Mapped[str] = mapped_column(String(64))
    min_sample_per_variant: Mapped[int] = mapped_column(Integer, default=200)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_origin: Mapped[str] = mapped_column(String(10), default="demo")


class ExperimentVariant(IdMixin, Base):
    __tablename__ = "experiment_variants"
    __table_args__ = (UniqueConstraint("experiment_id", "key"),)

    experiment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    is_control: Mapped[bool] = mapped_column(default=False)
    weight: Mapped[float] = mapped_column(Float, default=0.5)
    sequence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sequences.id", ondelete="SET NULL"))


class ExperimentAssignment(IdMixin, Base):
    __tablename__ = "experiment_assignments"
    __table_args__ = (UniqueConstraint("experiment_id", "unit_id"),)

    experiment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("experiment_variants.id", ondelete="CASCADE"))
    unit_id: Mapped[uuid.UUID] = mapped_column()
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bucket: Mapped[int] = mapped_column(Integer)


class ExperimentOutcome(IdMixin, Base):
    __tablename__ = "experiment_outcomes"
    __table_args__ = (UniqueConstraint("assignment_id", "metric"),)

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiment_assignments.id", ondelete="CASCADE")
    )
    metric: Mapped[str] = mapped_column(String(40))
    value: Mapped[float] = mapped_column(Float, default=1.0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_activity_id: Mapped[uuid.UUID | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text)
