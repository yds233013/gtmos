"""The mini-CRM: accounts, contacts, buying roles, pipeline, activities and behavioral engagement."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from gtmos.models.base import Base, IdMixin, TimestampMixin

# Account funnel stages (the GTM funnel), in order. Won/Lost are terminal.
FUNNEL_STAGES = (
    "prospect",
    "contacted",
    "engaged",
    "qualified",
    "meeting",
    "opportunity",
    "won",
    "lost",
)
# Deal stages inside the Opportunity funnel stage.
DEAL_STAGES = ("discovery", "evaluation", "proposal", "negotiation", "closed_won", "closed_lost")

# HubSpot-compatible lifecycle stages.
LIFECYCLE_STAGES = (
    "subscriber",
    "lead",
    "marketingqualifiedlead",
    "salesqualifiedlead",
    "opportunity",
    "customer",
    "evangelist",
    "other",
)

BUYING_ROLES = ("champion", "technical_evaluator", "economic_buyer", "executive_sponsor", "end_user")


class Account(IdMixin, TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        Index("ix_accounts_workspace_score", "workspace_id", "icp_score"),
        Index("ix_accounts_workspace_domain", "workspace_id", "domain"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(300))
    domain: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(String(120))
    sub_industry: Mapped[str | None] = mapped_column(String(120))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    employee_growth_12m: Mapped[float | None] = mapped_column(Float)  # fraction, 0.25 = +25%
    annual_revenue_usd: Mapped[int | None] = mapped_column(BigInteger)
    founded_year: Mapped[int | None] = mapped_column(Integer)
    country: Mapped[str | None] = mapped_column(String(2))  # ISO-3166 alpha-2
    region: Mapped[str | None] = mapped_column(String(10))  # NA | EMEA | APAC | LATAM
    city: Mapped[str | None] = mapped_column(String(120))
    funding_stage: Mapped[str | None] = mapped_column(String(40))
    total_funding_usd: Mapped[int | None] = mapped_column(BigInteger)
    last_funding_at: Mapped[date | None] = mapped_column(Date)
    last_funding_amount_usd: Mapped[int | None] = mapped_column(BigInteger)
    technologies: Mapped[list[Any]] = mapped_column(default=list)
    ai_team_size: Mapped[int | None] = mapped_column(Integer)
    ai_open_roles: Mapped[int | None] = mapped_column(Integer)
    linkedin_url: Mapped[str | None] = mapped_column(String(500))

    # GTM state
    segment: Mapped[str | None] = mapped_column(String(20))  # strategic | enterprise | mid_market | smb
    funnel_stage: Mapped[str] = mapped_column(String(20), default="prospect")
    lifecycle_stage: Mapped[str] = mapped_column(String(40), default="lead")
    is_customer: Mapped[bool] = mapped_column(default=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(60), default="demo_seed")
    data_origin: Mapped[str] = mapped_column(String(10), default="demo")
    is_flagship: Mapped[bool] = mapped_column(default=False)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))

    # Cached score (source of truth is icp_scores; these columns make list views and sorting cheap).
    icp_score: Mapped[int | None] = mapped_column(Integer)
    score_grade: Mapped[str | None] = mapped_column(String(2))  # A | B | C | D | X (excluded)
    intent_score: Mapped[int | None] = mapped_column(Integer)
    score_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    hubspot_company_id: Mapped[str | None] = mapped_column(String(40))


class Contact(IdMixin, TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_workspace_email", "workspace_id", "email"),
        Index("ix_contacts_account", "account_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(320))
    email_status: Mapped[str] = mapped_column(String(20), default="unknown")  # valid|invalid|risky|unknown
    title: Mapped[str | None] = mapped_column(String(200))
    seniority: Mapped[str | None] = mapped_column(String(30))  # c_suite|vp|director|manager|ic
    department: Mapped[str | None] = mapped_column(String(60))  # engineering|ai_ml|data|product|...
    persona: Mapped[str | None] = mapped_column(String(60))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    country: Mapped[str | None] = mapped_column(String(2))
    lifecycle_stage: Mapped[str] = mapped_column(String(40), default="lead")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(60), default="demo_seed")
    data_origin: Mapped[str] = mapped_column(String(10), default="demo")
    do_not_contact: Mapped[bool] = mapped_column(default=False)
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    hubspot_contact_id: Mapped[str | None] = mapped_column(String(40))

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p) or (self.email or "Unknown")


class AccountContactRole(IdMixin, TimestampMixin, Base):
    """A contact's inferred (or manually set) role on an account's buying committee."""

    __tablename__ = "account_contact_roles"
    __table_args__ = (UniqueConstraint("account_id", "contact_id", "role"),)

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(40))
    rank: Mapped[int] = mapped_column(Integer)  # 1 = primary holder of this role
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[list[Any]] = mapped_column(default=list)  # list of human-readable reasons
    is_manual_override: Mapped[bool] = mapped_column(default=False)
    overridden_by: Mapped[str | None] = mapped_column(String(200))


class PipelineStage(IdMixin, Base):
    __tablename__ = "pipeline_stages"
    __table_args__ = (UniqueConstraint("workspace_id", "pipeline", "key"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    pipeline: Mapped[str] = mapped_column(String(20))  # funnel | deal
    key: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer)
    probability: Mapped[float] = mapped_column(Float, default=0.0)
    is_closed: Mapped[bool] = mapped_column(default=False)
    is_won: Mapped[bool] = mapped_column(default=False)


class StageTransition(IdMixin, Base):
    """History of funnel/deal stage changes. Drives conversion, velocity and transition-validity checks."""

    __tablename__ = "stage_transitions"
    __table_args__ = (Index("ix_stage_transitions_entity", "entity_type", "entity_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    entity_type: Mapped[str] = mapped_column(String(20))  # account | opportunity
    entity_id: Mapped[uuid.UUID] = mapped_column()
    pipeline: Mapped[str] = mapped_column(String(20))
    from_stage: Mapped[str | None] = mapped_column(String(40))
    to_stage: Mapped[str] = mapped_column(String(40))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changed_by: Mapped[str] = mapped_column(String(200), default="system")
    reason: Mapped[str | None] = mapped_column(Text)


class Opportunity(IdMixin, TimestampMixin, Base):
    __tablename__ = "opportunities"
    __table_args__ = (Index("ix_opportunities_workspace_created", "workspace_id", "opened_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(300))
    stage: Mapped[str] = mapped_column(String(40), default="discovery")
    amount_usd: Mapped[float] = mapped_column(Numeric(14, 2, asdecimal=False), default=0)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    primary_contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    source_campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"))
    lead_source: Mapped[str | None] = mapped_column(String(60))  # outbound | inbound | plg | partner
    lost_reason: Mapped[str | None] = mapped_column(String(200))
    data_origin: Mapped[str] = mapped_column(String(10), default="demo")
    hubspot_deal_id: Mapped[str | None] = mapped_column(String(40))


class Activity(IdMixin, Base):
    """A sales touch or outcome: email events, replies, calls, meetings, tasks, notes."""

    __tablename__ = "activities"
    __table_args__ = (
        Index("ix_activities_account_time", "account_id", "occurred_at"),
        Index("ix_activities_workspace_type_time", "workspace_id", "type", "occurred_at"),
        UniqueConstraint("dedupe_key"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(40))
    channel: Mapped[str | None] = mapped_column(String(20))  # email | linkedin | phone | meeting | web
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"))
    sequence_step_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sequence_steps.id", ondelete="SET NULL"))
    message_draft_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("message_drafts.id", ondelete="SET NULL"))
    subject: Mapped[str | None] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(20))  # tasks: open | done
    properties: Mapped[dict[str, Any]] = mapped_column(default=dict)
    source: Mapped[str] = mapped_column(String(60), default="demo_seed")
    data_origin: Mapped[str] = mapped_column(String(10), default="demo")
    dedupe_key: Mapped[str | None] = mapped_column(String(200))


class Engagement(IdMixin, Base):
    """A behavioral event (product usage or website visit), typically ingested from PostHog."""

    __tablename__ = "engagements"
    __table_args__ = (
        Index("ix_engagements_account_time", "account_id", "occurred_at"),
        UniqueConstraint("dedupe_key"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    event_name: Mapped[str] = mapped_column(String(120))
    distinct_id: Mapped[str | None] = mapped_column(String(320))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    properties: Mapped[dict[str, Any]] = mapped_column(default=dict)
    source: Mapped[str] = mapped_column(String(40), default="demo_seed")  # posthog | web | demo_seed
    data_origin: Mapped[str] = mapped_column(String(10), default="demo")
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
