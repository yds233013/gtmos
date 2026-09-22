"""Automation and operations: workflows, routing, integrations, webhooks, audit and data quality."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from gtmos.models.base import Base, IdMixin, JSONType, TimestampMixin

WORKFLOW_RUN_STATUSES = ("queued", "running", "succeeded", "failed", "skipped", "dead_letter")
STEP_STATUSES = ("pending", "running", "succeeded", "failed", "skipped", "retrying")


class Workflow(IdMixin, TimestampMixin, Base):
    """TRIGGER → CONDITIONS → ACTIONS. `definition` is validated by domain.workflows.WorkflowDefinition."""

    __tablename__ = "workflows"
    __table_args__ = (UniqueConstraint("workspace_id", "key"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    trigger_type: Mapped[str] = mapped_column(String(60))
    definition: Mapped[dict[str, Any]] = mapped_column()
    is_enabled: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class WorkflowRun(IdMixin, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        Index("ix_workflow_runs_workspace_time", "workspace_id", "created_at"),
        Index("ix_workflow_runs_account", "account_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    workflow_version: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    trigger_event: Mapped[dict[str, Any]] = mapped_column(default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    correlation_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    condition_results: Mapped[list[Any]] = mapped_column(default=list)
    error: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_origin: Mapped[str] = mapped_column(String(10), default="demo")


class WorkflowStepRun(IdMixin, Base):
    __tablename__ = "workflow_step_runs"
    __table_args__ = (UniqueConstraint("run_id", "step_key"),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    step_key: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    input: Mapped[dict[str, Any]] = mapped_column(default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    logs: Mapped[list[Any]] = mapped_column(default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class RoutingRule(IdMixin, TimestampMixin, Base):
    __tablename__ = "routing_rules"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer)  # lower number wins
    conditions: Mapped[list[Any]] = mapped_column(default=list)  # [{field, op, value}]
    assign_strategy: Mapped[str] = mapped_column(String(20))  # user | pool_least_loaded
    assign_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assign_team: Mapped[str | None] = mapped_column(String(80))
    overrides_existing_owner: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)


class RoutingDecision(IdMixin, Base):
    __tablename__ = "routing_decisions"
    __table_args__ = (Index("ix_routing_decisions_account", "account_id", "decided_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("routing_rules.id", ondelete="SET NULL"))
    outcome: Mapped[str] = mapped_column(String(20))  # assigned | kept_owner | unmatched
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    previous_owner_id: Mapped[uuid.UUID | None] = mapped_column()
    matched_rules: Mapped[list[Any]] = mapped_column(default=list)
    conflicts: Mapped[list[Any]] = mapped_column(default=list)
    explanation: Mapped[list[Any]] = mapped_column(default=list)
    trigger: Mapped[str] = mapped_column(String(60), default="manual")
    latency_ms: Mapped[float | None] = mapped_column(Float)  # signal→decision latency when triggered by one
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied: Mapped[bool] = mapped_column(default=True)


class Integration(IdMixin, TimestampMixin, Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("workspace_id", "provider"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40))  # crm | enrichment | product_analytics | ...
    mode: Mapped[str] = mapped_column(String(10))  # demo | live | disabled
    status: Mapped[str] = mapped_column(String(20), default="healthy")
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)  # non-secret settings only
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class IntegrationSync(IdMixin, Base):
    __tablename__ = "integration_syncs"
    __table_args__ = (Index("ix_integration_syncs_time", "workspace_id", "started_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(40))
    job: Mapped[str] = mapped_column(String(60))  # e.g. reverse_etl_companies, crm_upsert_contacts
    direction: Mapped[str] = mapped_column(String(10))  # outbound | inbound
    object_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))  # running | succeeded | partial | failed
    is_simulated: Mapped[bool] = mapped_column(default=True)
    records_considered: Mapped[int] = mapped_column(Integer, default=0)
    records_changed: Mapped[int] = mapped_column(Integer, default=0)
    records_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    records_failed: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[Any]] = mapped_column(default=list)
    correlation_id: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(60), default="manual")


class ExternalRecord(IdMixin, Base):
    """Maps a GTMOS record to its id in an external system, with the hash of what we last pushed.

    This is the backbone of idempotent sync: unchanged payloads are skipped, and a record is
    never created twice in the destination because we upsert on a stable key.
    """

    __tablename__ = "external_records"
    __table_args__ = (
        UniqueConstraint("provider", "object_type", "internal_id"),
        Index("ix_external_records_external", "provider", "object_type", "external_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(40))
    object_type: Mapped[str] = mapped_column(String(40))
    internal_id: Mapped[uuid.UUID] = mapped_column()
    external_id: Mapped[str | None] = mapped_column(String(64))
    last_payload_hash: Mapped[str | None] = mapped_column(String(64))
    last_payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remote_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_simulated: Mapped[bool] = mapped_column(default=True)


class WebhookEvent(IdMixin, Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("source", "idempotency_key"),
        Index("ix_webhook_events_time", "workspace_id", "received_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(40))  # posthog | n8n | hubspot | generic
    event_type: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    signature_status: Mapped[str] = mapped_column(String(20))  # valid | invalid | not_configured
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20))  # processed | failed | rejected | dead_letter
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    correlation_id: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_ms: Mapped[int | None] = mapped_column(Integer)
    data_origin: Mapped[str] = mapped_column(String(10), default="demo")


class AuditEvent(IdMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_time", "workspace_id", "occurred_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    actor_type: Mapped[str] = mapped_column(String(20))  # user | system | workflow | integration
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID | None] = mapped_column()
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    reason: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DataQualityIssue(IdMixin, Base):
    __tablename__ = "data_quality_issues"
    __table_args__ = (
        UniqueConstraint("workspace_id", "fingerprint"),
        Index("ix_dq_issues_status", "workspace_id", "status", "rule_key"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    rule_key: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(10))  # high | medium | low
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[uuid.UUID | None] = mapped_column()
    related_ids: Mapped[list[Any]] = mapped_column(default=list)
    title: Mapped[str] = mapped_column(String(300))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    suggested_fix: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {action, params, description}
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved | ignored
    fingerprint: Mapped[str] = mapped_column(String(64))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(200))


class SimulatedCrmObject(IdMixin, Base):
    """What the *demo* HubSpot adapter "stores". Lets the UI show the simulated remote side honestly."""

    __tablename__ = "simulated_crm_objects"
    __table_args__ = (UniqueConstraint("workspace_id", "object_type", "external_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    object_type: Mapped[str] = mapped_column(String(40))  # companies | contacts | deals | notes | tasks
    external_id: Mapped[str] = mapped_column(String(64))
    unique_key: Mapped[str | None] = mapped_column(String(320))  # domain / email used for upsert
    properties: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
