"""Workflow definitions: TRIGGER → CONDITIONS → ACTIONS, as validated data."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from gtmos.domain.rules import Condition

TriggerType = Literal[
    "signal.created",
    "score.threshold_crossed",
    "product.pql",
    "account.created",
    "manual",
]

ACTIONS: dict[str, str] = {
    "enrich_account": "Run the enrichment waterfall for the account",
    "recalculate_score": "Recompute the explainable ICP score",
    "identify_buying_committee": "Infer champion, evaluator, economic buyer, sponsor and end users",
    "generate_research": "Produce an evidence-grounded research brief (draft)",
    "draft_outreach": "Draft personalized outreach for the champion and put it in the approval queue",
    "route_account": "Run routing rules and assign an owner",
    "create_task": "Create a follow-up task for the owner",
    "update_lifecycle": "Advance funnel stage / lifecycle (forward-only)",
    "sync_crm": "Upsert the account and GTMOS properties to the CRM",
    "notify_owner": "Record an owner notification (no external message is sent)",
}


class TriggerSpec(BaseModel):
    type: TriggerType
    filters: list[Condition] = Field(default_factory=list)


class StepSpec(BaseModel):
    key: str
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=10)
    continue_on_failure: bool = False

    @model_validator(mode="after")
    def _known_action(self) -> StepSpec:
        if self.action not in ACTIONS:
            raise ValueError(f"unknown action '{self.action}'")
        return self


class WorkflowDefinition(BaseModel):
    trigger: TriggerSpec
    conditions: list[Condition] = Field(default_factory=list)
    steps: list[StepSpec]

    @model_validator(mode="after")
    def _unique_steps(self) -> WorkflowDefinition:
        keys = [s.key for s in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError("step keys must be unique")
        if not self.steps:
            raise ValueError("a workflow needs at least one step")
        return self


def idempotency_key(workflow_key: str, version: int, trigger_type: str, event_id: str) -> str:
    """One run per (workflow version, trigger event). Re-delivered events don't re-run workflows."""
    return f"wf:{workflow_key}:v{version}:{trigger_type}:{event_id}"


# Retry backoff (seconds) used by the queue worker between attempts: 2s, 8s, 32s...
def backoff_seconds(attempt: int, base: float = 2.0, factor: float = 4.0, cap: float = 300.0) -> float:
    return float(min(base * (factor ** max(attempt - 1, 0)), cap))


DEFAULT_WORKFLOWS: list[dict[str, Any]] = [
    {
        "key": "funding-signal-to-outreach",
        "name": "Funding signal → research → outreach draft",
        "description": (
            "When a high-fit account raises money, enrich it, find the buying committee, generate "
            "evidence-grounded research, draft outreach into the approval queue, route and sync to CRM."
        ),
        "definition": {
            "trigger": {"type": "signal.created",
                        "filters": [{"field": "signal.signal_type", "op": "in",
                                     "value": ["funding_round", "ai_product_launch"]}]},
            "conditions": [
                {"field": "account.icp_score", "op": "gte", "value": 75},
                {"field": "account.is_customer", "op": "eq", "value": False},
            ],
            "steps": [
                {"key": "enrich", "action": "enrich_account"},
                {"key": "rescore", "action": "recalculate_score"},
                {"key": "committee", "action": "identify_buying_committee"},
                {"key": "research", "action": "generate_research"},
                {"key": "draft", "action": "draft_outreach", "params": {"channel": "email"}},
                {"key": "route", "action": "route_account"},
                {"key": "crm", "action": "sync_crm", "max_attempts": 4},
            ],
        },
    },
    {
        "key": "pql-to-ae",
        "name": "Product-qualified account → AE",
        "description": (
            "When product usage crosses the PQL threshold, route enterprise-tier accounts to an AE, "
            "create a follow-up task, advance lifecycle and sync."
        ),
        "definition": {
            "trigger": {"type": "product.pql", "filters": []},
            "conditions": [
                {"field": "account.segment", "op": "in", "value": ["strategic", "enterprise", "mid_market"]},
            ],
            "steps": [
                {"key": "rescore", "action": "recalculate_score"},
                {"key": "route", "action": "route_account"},
                {"key": "task", "action": "create_task",
                 "params": {"subject": "PQL: reach out within 1 business day"}},
                {"key": "lifecycle", "action": "update_lifecycle", "params": {"stage": "engaged"}},
                {"key": "notify", "action": "notify_owner"},
                {"key": "crm", "action": "sync_crm", "max_attempts": 4},
            ],
        },
    },
    {
        "key": "ai-hiring-surge-enrichment",
        "name": "AI hiring surge → enrich & rescore",
        "description": "Re-enrich and rescore accounts whose AI team is scaling quickly.",
        "definition": {
            "trigger": {"type": "signal.created",
                        "filters": [{"field": "signal.signal_type", "op": "eq", "value": "ai_hiring_surge"}]},
            "conditions": [{"field": "account.score_grade", "op": "in", "value": ["A", "B", "C"]}],
            "steps": [
                {"key": "enrich", "action": "enrich_account"},
                {"key": "rescore", "action": "recalculate_score"},
                {"key": "committee", "action": "identify_buying_committee"},
            ],
        },
    },
    {
        "key": "score-threshold-routing",
        "name": "Score crosses 80 → route to owner",
        "description": "When an account becomes A-grade, make sure it has an owner and a task.",
        "definition": {
            "trigger": {"type": "score.threshold_crossed",
                        "filters": [{"field": "event.threshold", "op": "eq", "value": 80}]},
            "conditions": [],
            "steps": [
                {"key": "route", "action": "route_account"},
                {"key": "task", "action": "create_task",
                 "params": {"subject": "Newly A-grade account: review research and committee"}},
                {"key": "crm", "action": "sync_crm"},
            ],
        },
    },
]
