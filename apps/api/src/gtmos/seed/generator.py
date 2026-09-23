"""Deterministic DEMO dataset.

Everything here is synthetic and reproducible (fixed RNG seeds, uuid5 ids, `.example` domains) and is
stored with data_origin='demo'. The data isn't random noise: each account has a latent propensity
(AI maturity × fit) that drives signals, replies, meetings and wins. The analytics therefore contain
real structure to discover: higher-scored accounts convert better, funding-trigger messaging beats
generic messaging, pipeline creation dips after the funding campaign ends, and APAC accounts stall
because no routing rule covers them. Those patterns follow from the simulation rules below; no
metric is hardcoded.
"""

from __future__ import annotations

import logging
import math
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from gtmos.domain.experiments import assign_variant
from gtmos.domain.icp import default_icp
from gtmos.domain.personalization import PersonalizationInput, generate_messages
from gtmos.domain.pipeline import FUNNEL_TO_LIFECYCLE
from gtmos.domain.research import ANGLES
from gtmos.domain.rules import Condition, evaluate_all
from gtmos.domain.signals import SIGNAL_TYPES, signal_dedupe_key
from gtmos.domain.workflows import DEFAULT_WORKFLOWS
from gtmos.models import (
    Account,
    Activity,
    AuditEvent,
    Campaign,
    Contact,
    Engagement,
    Experiment,
    ExperimentAssignment,
    ExperimentOutcome,
    ExperimentVariant,
    FieldProvenance,
    ICPProfile,
    Integration,
    IntegrationSync,
    MessageDraft,
    Opportunity,
    PipelineStage,
    RoutingRule,
    Sequence,
    SequenceStep,
    Signal,
    SignalType,
    StageTransition,
    User,
    WebhookEvent,
    Workflow,
    WorkflowRun,
    WorkflowStepRun,
    Workspace,
)
from gtmos.models.crm import DEAL_STAGES, FUNNEL_STAGES
from gtmos.seed.profiles import FLAGSHIP, CompanyProfile, company_universe, segment_for
from gtmos.services.common import jsonable

log = logging.getLogger(__name__)
NS = uuid.UUID("6f1c2a8e-3b1d-4d5e-9a7b-0c1d2e3f4a5b")
RNG_SEED = 7


def uid(kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"{kind}:{key}")


FIRST = [
    "Alex",
    "Ana",
    "Arjun",
    "Ben",
    "Camila",
    "Chen",
    "Daniel",
    "Elena",
    "Emeka",
    "Fatima",
    "Gabriel",
    "Hana",
    "Ian",
    "Isabel",
    "Jin",
    "Jonas",
    "Kai",
    "Keisha",
    "Lars",
    "Leila",
    "Lucas",
    "Mei",
    "Mateo",
    "Nadia",
    "Noah",
    "Olga",
    "Omar",
    "Priyanka",
    "Rafael",
    "Rhea",
    "Sara",
    "Sofia",
    "Tariq",
    "Theo",
    "Uma",
    "Victor",
    "Wei",
    "Yara",
    "Yusuf",
    "Zoe",
    "Hiro",
    "Amara",
    "Diego",
    "Freya",
    "Ines",
    "Kofi",
    "Liam",
    "Nia",
]
LAST = [
    "Abe",
    "Adeyemi",
    "Alvarez",
    "Andersen",
    "Bauer",
    "Bose",
    "Castro",
    "Cohen",
    "Dubois",
    "Eriksen",
    "Fernandes",
    "Garcia",
    "Gupta",
    "Haddad",
    "Ito",
    "Jansen",
    "Kaur",
    "Kim",
    "Kowalski",
    "Larsen",
    "Liu",
    "Mehta",
    "Moreau",
    "Nakamura",
    "Novak",
    "Okafor",
    "Olsen",
    "Park",
    "Petrov",
    "Quinn",
    "Rossi",
    "Sato",
    "Schmidt",
    "Silva",
    "Singh",
    "Tanaka",
    "Torres",
    "Ueda",
    "Varga",
    "Wang",
    "Weber",
    "Yilmaz",
    "Zhang",
]

# (title, seniority, department, weight)
TITLES: list[tuple[str, str, str, float]] = [
    ("Chief Technology Officer", "c_suite", "engineering", 0.6),
    ("VP Engineering", "vp", "engineering", 0.8),
    ("VP of AI", "vp", "ai_ml", 0.4),
    ("Head of AI", "director", "ai_ml", 0.6),
    ("Head of Machine Learning", "director", "ai_ml", 0.5),
    ("Director of AI Infrastructure", "director", "ai_ml", 0.4),
    ("ML Platform Lead", "manager", "ai_ml", 0.5),
    ("Staff ML Engineer", "ic", "ai_ml", 0.6),
    ("Principal Engineer, ML Platform", "ic", "ai_ml", 0.4),
    ("ML Engineer", "ic", "ai_ml", 1.0),
    ("Senior Data Scientist", "ic", "data", 0.6),
    ("Engineering Manager, Applied AI", "manager", "ai_ml", 0.4),
    ("Software Engineer", "ic", "engineering", 0.6),
    ("Head of Data", "director", "data", 0.4),
    ("VP Marketing", "vp", "marketing", 0.3),
    ("Account Executive", "ic", "sales", 0.3),
    ("Head of People", "director", "hr", 0.2),
    ("Product Manager, AI", "manager", "product", 0.4),
]
INVESTORS = [
    "Harbor Ridge Ventures",
    "Northfield Capital",
    "Lattice Partners",
    "Crescent Growth",
    "Bluewater Ventures",
    "Summit Peak Capital",
]
PRODUCT_WORDS = ["Assist", "Copilot", "Agent", "Autopilot", "Insights AI", "Answers"]
JOB_POSTINGS = [
    "Staff Engineer, LLM Evaluation",
    "ML Platform Engineer (LLM Ops)",
    "AI Reliability Engineer",
    "Senior Engineer, Agent Infrastructure",
    "Applied Scientist, Model Evaluation",
]
EXEC_TITLES = ["VP of AI", "Head of Machine Learning", "CTO", "VP Engineering"]
REGION_OFFICES = {
    "NA": ["Austin", "Toronto", "New York"],
    "EMEA": ["London", "Berlin", "Amsterdam"],
    "APAC": ["Singapore", "Sydney"],
    "LATAM": ["São Paulo"],
}

CAMPAIGNS = [
    # key, name, start_offset_days, end_offset_days(None=active), trigger, persona, hypothesis, segment
    (
        "funding-trigger",
        "Series B–D funding trigger",
        -170,
        -38,
        "funding_round",
        "Head of AI",
        "Accounts that just raised will prioritize AI reliability; referencing the round lifts replies.",
        {"signals": ["funding_round"], "grades": ["A", "B"]},
    ),
    (
        "agent-launch",
        "AI agent launch → reliability",
        -95,
        None,
        "ai_product_launch",
        "Head of AI",
        "Teams that just shipped an agent feel production reliability pain immediately.",
        {"signals": ["ai_product_launch"]},
    ),
    (
        "icp-generic",
        "ICP: AI platform leaders (generic)",
        -180,
        None,
        None,
        "VP Engineering",
        "Baseline ICP outreach without a timing trigger.",
        {"grades": ["A", "B", "C"]},
    ),
    (
        "plg-to-prod",
        "PLG: free workspace → production",
        -120,
        None,
        "usage_threshold",
        "ML Platform Lead",
        "Active free workspaces convert when offered a production rollout plan.",
        {"signals": ["product_signup"]},
    ),
    (
        "emea-ai-infra",
        "EMEA AI infrastructure",
        -110,
        None,
        None,
        "Head of ML",
        "Regional messaging for EMEA AI teams (data residency angle).",
        {"regions": ["EMEA"]},
    ),
    (
        "webinar-agents",
        "Webinar: Evaluating LLM agents in production",
        -100,
        -100,
        None,
        "ML Engineer",
        "Educational content creates inbound engagement from practitioners.",
        {},
    ),
]
# The provocative-subject arm. The extra replies the curiosity-gap subject earns are not buying intent —
# it is the same offer in the same email, so the people who were going to be interested were already
# replying. Most of the extra volume is an explicit brush-off; the rest goes nowhere.
# Applied as a pass over the experiment's outcome rows once the journeys have run, never by nudging a
# probability inside `_journey` — the journey's RNG draws are conditional on its own branches, so moving
# one threshold desynchronises the stream for every account after it and silently rewrites the whole
# dataset. Outcomes feed the experiments page and nothing else, so this arm distorts nothing upstream.
CURIOSITY_EXTRA_REPLY_P = 0.22
CURIOSITY_HOSTILE_SHARE = 0.42
# Unsubscribes and spam complaints have no simulated activity of their own, so they are drawn per account
# from a generator seeded off the account id: deterministic, and independent of the main RNG stream, so
# adding them moves no other number in the dataset. (unsubscribe rate, spam complaint rate) per arm.
GUARDRAIL_RATES: dict[str, tuple[float, float]] = {
    "funding-vs-generic:control": (0.0040, 0.0003),
    "funding-vs-generic:treatment": (0.0050, 0.0003),
    "subject-question:control": (0.0050, 0.0005),
    "subject-question:treatment": (0.0110, 0.0010),
    "provocative-subject:control": (0.0050, 0.0005),
    "provocative-subject:treatment": (0.0300, 0.0040),
}
REPLY_MULTIPLIER = {
    "funding-trigger:treatment": 1.9,
    "funding-trigger:control": 1.0,
    "agent-launch": 1.6,
    "icp-generic": 1.0,
    "plg-to-prod": 2.3,
    "emea-ai-infra": 0.75,
}
OPP_AMOUNT = {
    "smb": (12_000, 30_000),
    "mid_market": (30_000, 70_000),
    "enterprise": (60_000, 160_000),
    "strategic": (120_000, 320_000),
}


@dataclass
class Ctx:
    db: Session
    ws: Workspace
    anchor: datetime
    rng: random.Random
    users: dict[str, User] = field(default_factory=dict)
    campaigns: dict[str, Campaign] = field(default_factory=dict)
    steps: dict[str, list[SequenceStep]] = field(default_factory=dict)
    experiments: dict[str, Experiment] = field(default_factory=dict)
    variants: dict[str, dict[str, ExperimentVariant]] = field(default_factory=dict)
    accounts: list[Account] = field(default_factory=list)
    profiles: dict[uuid.UUID, CompanyProfile] = field(default_factory=dict)
    contacts: dict[uuid.UUID, list[Contact]] = field(default_factory=lambda: defaultdict(list))
    signals: dict[uuid.UUID, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    activity_rows: list[dict[str, Any]] = field(default_factory=list)
    engagement_rows: list[dict[str, Any]] = field(default_factory=list)
    transition_rows: list[dict[str, Any]] = field(default_factory=list)
    signal_rows: list[dict[str, Any]] = field(default_factory=list)
    audit_rows: list[dict[str, Any]] = field(default_factory=list)
    opp_rows: list[dict[str, Any]] = field(default_factory=list)
    assignment_rows: list[dict[str, Any]] = field(default_factory=list)
    outcome_rows: list[dict[str, Any]] = field(default_factory=list)
    draft_rows: list[dict[str, Any]] = field(default_factory=list)
    counter: int = 0

    def d(self, days: float) -> datetime:
        return self.anchor + timedelta(days=days)

    def key(self, prefix: str) -> str:
        self.counter += 1
        return f"seed:{prefix}:{self.counter}"


# --------------------------------------------------------------------------------------------------
# Static configuration
# --------------------------------------------------------------------------------------------------


def _users(c: Ctx) -> None:
    spec = [
        ("sam", "Sam Okoro", "senior_ae", "Strategic", "NA", "Senior Account Executive", 60, True),
        ("avery", "Avery Brooks", "ae", "Enterprise NA", "NA", "Account Executive", 220, True),
        ("jordan", "Jordan Patel", "ae", "Enterprise NA", "NA", "Account Executive", 220, True),
        ("chris", "Chris Walker", "ae", "Enterprise NA", "NA", "Account Executive (departed)", 220, False),
        ("lena", "Lena Fischer", "ae", "Enterprise EMEA", "EMEA", "Account Executive", 220, True),
        ("tom", "Tom Hughes", "ae", "Enterprise EMEA", "EMEA", "Account Executive", 220, True),
        ("casey", "Casey Nguyen", "sdr", "SDR Pool", None, "Sales Development Rep", 450, True),
        ("drew", "Drew Martinez", "sdr", "SDR Pool", None, "Sales Development Rep", 450, True),
        ("maya", "Maya Lopez", "sdr", "SDR Pool", None, "Sales Development Rep", 450, True),
        ("morgan", "Morgan Reyes", "am", "Account Management", None, "Account Manager", 150, True),
        ("riley", "Riley Chen", "revops", "RevOps", None, "GTM Engineer / RevOps", 0, True),
    ]
    for key, name, role, team, terr, title, cap, active in spec:
        u = User(
            id=uid("user", key),
            workspace_id=c.ws.id,
            name=name,
            email=f"{name.split()[0].lower()}@sentinel-ai.example",
            role=role,
            team=team,
            territory=terr,
            title=title,
            capacity=cap,
            is_active=active,
        )
        c.db.add(u)
        c.users[key] = u


def _stages_and_types(c: Ctx) -> None:
    probs = {
        "prospect": 0.0,
        "contacted": 0.02,
        "engaged": 0.05,
        "qualified": 0.1,
        "meeting": 0.2,
        "opportunity": 0.35,
        "won": 1.0,
        "lost": 0.0,
    }
    for i, s in enumerate(FUNNEL_STAGES):
        c.db.add(
            PipelineStage(
                workspace_id=c.ws.id,
                pipeline="funnel",
                key=s,
                name=s.title(),
                position=i,
                probability=probs[s],
                is_closed=s in ("won", "lost"),
                is_won=s == "won",
            )
        )
    dprobs = [0.15, 0.3, 0.55, 0.75, 1.0, 0.0]
    for i, s in enumerate(DEAL_STAGES):
        c.db.add(
            PipelineStage(
                workspace_id=c.ws.id,
                pipeline="deal",
                key=s,
                name=s.replace("_", " ").title(),
                position=i,
                probability=dprobs[i],
                is_closed=s.startswith("closed"),
                is_won=s == "closed_won",
            )
        )
    existing = set(c.db.scalars(select(SignalType.key)))
    for spec in SIGNAL_TYPES.values():
        if spec.key not in existing:
            c.db.add(
                SignalType(
                    key=spec.key,
                    name=spec.name,
                    category=spec.category,
                    default_strength=spec.default_strength,
                    half_life_days=spec.half_life_days,
                    description=spec.description,
                )
            )


def _icp_rules_workflows_integrations(c: Ctx) -> None:
    icp = default_icp()
    c.db.add(
        ICPProfile(
            id=uid("icp", "v1"),
            workspace_id=c.ws.id,
            name=icp.name,
            version=1,
            is_active=True,
            definition=icp.model_dump(mode="json"),
            created_by="seed",
        )
    )
    U = c.users
    rules = [
        (
            "existing-customer",
            "Existing customer → Account Management",
            10,
            [{"field": "account.is_customer", "op": "eq", "value": True}],
            "pool_least_loaded",
            None,
            "Account Management",
            True,
            "Customers are expansion motions owned by AMs, even if an AE sourced them.",
        ),
        (
            "strategic-high-intent",
            "High-intent strategic → Senior AE",
            20,
            [
                {"field": "account.segment", "op": "in", "value": ["strategic", "enterprise"]},
                {"field": "account.icp_score", "op": "gte", "value": 80},
                {"field": "account.intent_score", "op": "gte", "value": 55},
            ],
            "user",
            U["sam"].id,
            "Strategic",
            False,
            "Our best-fit, highest-intent large accounts get the senior AE immediately.",
        ),
        (
            "enterprise-na",
            "Enterprise NA → Enterprise AE pool",
            30,
            [
                {"field": "account.segment", "op": "in", "value": ["strategic", "enterprise"]},
                {"field": "account.region", "op": "eq", "value": "NA"},
            ],
            "pool_least_loaded",
            None,
            "Enterprise NA",
            False,
            "Territory rule for North American enterprise accounts.",
        ),
        (
            "enterprise-emea",
            "Enterprise EMEA → EMEA AE pool",
            30,
            [
                {"field": "account.segment", "op": "in", "value": ["strategic", "enterprise"]},
                {"field": "account.region", "op": "eq", "value": "EMEA"},
            ],
            "pool_least_loaded",
            None,
            "Enterprise EMEA",
            False,
            "Territory rule for EMEA enterprise accounts.",
        ),
        (
            "midmarket-high-intent",
            "High-intent mid-market NA → Enterprise AE pool",
            40,
            [
                {"field": "account.segment", "op": "eq", "value": "mid_market"},
                {"field": "account.region", "op": "eq", "value": "NA"},
                {"field": "account.intent_score", "op": "gte", "value": 60},
            ],
            "pool_least_loaded",
            None,
            "Enterprise NA",
            False,
            "Hot mid-market accounts skip the SDR stage.",
        ),
        (
            "smb-midmarket",
            "SMB & mid-market → SDR pool",
            50,
            [
                {"field": "account.segment", "op": "in", "value": ["mid_market", "smb"]},
                {"field": "account.region", "op": "in", "value": ["NA", "EMEA"]},
            ],
            # Round robin rather than least-loaded: SDR capacity is uniform, so even distribution is
            # fairer than load, and hashing the account keeps a replay landing on the same rep.
            "round_robin",
            None,
            "SDR Pool",
            False,
            "Everything else in covered regions starts with an SDR.",
        ),
        (
            "revops-triage",
            "Unrouted → RevOps triage queue",
            999,
            [],
            "pool_least_loaded",
            None,
            "Account Management",
            False,
            "Accounts no territory rule claims. A queue someone works, not an absence of an owner.",
        ),
    ]
    # Hours allowed between assignment and first outbound touch, per rule. Tighter where intent is
    # fresh: a high-intent account that waits a day has usually moved on.
    SLA_HOURS = {
        "existing-customer": 48,
        "strategic-high-intent": 4,
        "enterprise-na": 24,
        "enterprise-emea": 24,
        "midmarket-high-intent": 8,
        "smb-midmarket": 48,
        "revops-triage": 72,
    }
    for key, name, prio, conds, strat, user_id, team, override, desc in rules:
        c.db.add(
            RoutingRule(
                id=uid("rule", key),
                workspace_id=c.ws.id,
                key=key,
                name=name,
                description=desc,
                priority=prio,
                conditions=conds,
                assign_strategy=strat,
                assign_user_id=user_id,
                assign_team=team,
                overrides_existing_owner=override,
                is_active=True,
                sla_hours=SLA_HOURS.get(key),
                is_fallback=key == "revops-triage",
            )
        )
    for wf in DEFAULT_WORKFLOWS:
        c.db.add(
            Workflow(
                id=uid("workflow", wf["key"]),
                workspace_id=c.ws.id,
                key=wf["key"],
                name=wf["name"],
                description=wf["description"],
                trigger_type=wf["definition"]["trigger"]["type"],
                definition=wf["definition"],
                is_enabled=True,
                version=1,
            )
        )
    from gtmos.config import get_settings

    s = get_settings()
    integrations = [
        (
            "hubspot",
            "HubSpot CRM",
            "crm",
            "live" if s.hubspot_access_token and s.hubspot_live_writes_enabled else "demo",
            {"id_property": "gtmos_account_id", "batch_limit": 100},
        ),
        (
            "posthog",
            "PostHog (product events)",
            "product_analytics",
            "demo",
            {"endpoint": "/api/v1/webhooks/posthog", "group_key": "company"},
        ),
        ("demo_firmographics", "Firmographics DB (simulated)", "enrichment", "demo", {"cost_per_lookup": 1.0}),
        (
            "demo_webscan",
            "Website & technographics scanner (simulated)",
            "enrichment",
            "demo",
            {"cost_per_lookup": 0.5},
        ),
        ("demo_hiring", "Job-postings index (simulated)", "enrichment", "demo", {"cost_per_lookup": 0.75}),
        (
            "apollo",
            "Apollo organization enrichment",
            "enrichment",
            "live" if s.apollo_api_key else "disabled",
            {"note": "Optional real adapter; requires APOLLO_API_KEY"},
        ),
        ("anthropic", "Claude (research writer)", "llm", s.llm_mode, {"model": s.llm_model}),
        (
            "n8n",
            "n8n workflows",
            "workflow_automation",
            "demo",
            {"templates": "integrations/n8n/*.json", "endpoint": "/api/v1/webhooks/n8n"},
        ),
    ]
    for prov, name, cat, mode, cfg in integrations:
        c.db.add(
            Integration(
                workspace_id=c.ws.id,
                provider=prov,
                display_name=name,
                category=cat,
                mode=mode,
                status="healthy" if mode != "disabled" else "not_configured",
                config=cfg,
            )
        )


def _campaigns(c: Ctx) -> None:
    for key, name, start, end, trigger, persona, hyp, seg in CAMPAIGNS:
        status = "completed" if end is not None and end < 0 else "active"
        camp = Campaign(
            id=uid("campaign", key),
            workspace_id=c.ws.id,
            key=key,
            name=name,
            status=status,
            hypothesis=hyp,
            target_segment=seg,
            persona=persona,
            trigger_signal=trigger,
            channel="event" if key == "webinar-agents" else "email",
            value_prop="Evaluation gates and agent tracing for production AI.",
            start_date=c.d(start).date(),
            end_date=c.d(end).date() if end is not None else None,
            owner_id=c.users["riley"].id,
        )
        c.db.add(camp)
        c.campaigns[key] = camp
        if key == "webinar-agents":
            continue
        variants = ["control", "treatment"] if key == "funding-trigger" else [None]
        for v in variants:
            seq = Sequence(
                id=uid("sequence", f"{key}:{v}"),
                campaign_id=camp.id,
                name=f"{name}{f' ({v})' if v else ''}",
                variant_key=v,
            )
            c.db.add(seq)
            steps = []
            for n, (delay, subj) in enumerate(
                [(0, "{hook}: agent reliability"), (3, "Re: {hook}"), (8, "Worth a look?")], start=1
            ):
                st = SequenceStep(
                    id=uid("step", f"{key}:{v}:{n}"),
                    sequence_id=seq.id,
                    step_number=n,
                    channel="email",
                    delay_days=delay,
                    subject_template=subj,
                    body_template="Hi {first_name}, {opener} {value_prop} {cta}",
                )
                c.db.add(st)
                steps.append(st)
            c.steps[f"{key}:{v}" if v else key] = steps
    c.db.flush()  # no ORM relationships, so enforce FK insert order explicitly

    e1 = Experiment(
        id=uid("exp", "funding-vs-generic"),
        workspace_id=c.ws.id,
        key="funding-vs-generic",
        name="Funding-trigger personalization vs generic ICP messaging",
        hypothesis="Referencing a verified funding round increases positive reply rate.",
        null_hypothesis="Funding-trigger personalization performs the same as generic ICP messaging.",
        primary_metric="positive_reply",
        unit="account",
        status="stopped",
        salt="exp-funding-v1",
        min_sample_per_variant=120,
        campaign_id=c.campaigns["funding-trigger"].id,
        started_at=c.d(-170),
        ended_at=c.d(-38),
    )
    e2 = Experiment(
        id=uid("exp", "subject-question"),
        workspace_id=c.ws.id,
        key="subject-question",
        name="Subject line: question vs statement",
        hypothesis="A question subject line increases reply rate for launch-triggered outreach.",
        null_hypothesis="Subject line style has no effect on reply rate.",
        primary_metric="reply",
        unit="account",
        status="running",
        salt="exp-subject-v1",
        min_sample_per_variant=250,
        campaign_id=c.campaigns["agent-launch"].id,
        started_at=c.d(-21),
    )
    # The cautionary tale. Primary metric is bare reply rate — deliberately the metric a team reaches for
    # first — so the dataset contains a treatment that wins it and still must not ship.
    e3 = Experiment(
        id=uid("exp", "provocative-subject"),
        workspace_id=c.ws.id,
        key="provocative-subject",
        name="Provocative subject line vs plain value subject",
        hypothesis="A curiosity-gap subject line increases reply rate on the generic ICP play.",
        null_hypothesis="Subject-line framing has no effect on reply rate.",
        primary_metric="reply",
        unit="account",
        status="stopped",
        salt="exp-provocative-v1",
        min_sample_per_variant=250,
        campaign_id=c.campaigns["icp-generic"].id,
        started_at=c.d(-180),
        ended_at=c.d(-1),
    )
    for e in (e1, e2, e3):
        c.db.add(e)
        c.experiments[e.key] = e
    c.db.flush()
    c.variants["funding-vs-generic"] = {
        "control": ExperimentVariant(
            id=uid("variant", "e1c"),
            experiment_id=e1.id,
            key="control",
            name="Generic ICP personalization",
            is_control=True,
            weight=0.5,
            description="Persona pain + value prop; no trigger reference.",
            sequence_id=uid("sequence", "funding-trigger:control"),
        ),
        "treatment": ExperimentVariant(
            id=uid("variant", "e1t"),
            experiment_id=e1.id,
            key="treatment",
            name="Funding-trigger personalization",
            weight=0.5,
            description="Opens with the verified funding round and its implication.",
            sequence_id=uid("sequence", "funding-trigger:treatment"),
        ),
    }
    c.variants["subject-question"] = {
        "control": ExperimentVariant(
            id=uid("variant", "e2c"),
            experiment_id=e2.id,
            key="control",
            name="Statement subject",
            is_control=True,
            weight=0.5,
        ),
        "treatment": ExperimentVariant(
            id=uid("variant", "e2t"), experiment_id=e2.id, key="treatment", name="Question subject", weight=0.5
        ),
    }
    c.variants["provocative-subject"] = {
        "control": ExperimentVariant(
            id=uid("variant", "e3c"),
            experiment_id=e3.id,
            key="control",
            name="Plain value subject",
            is_control=True,
            weight=0.5,
            description="States the topic: '<Account>: agent reliability'.",
        ),
        "treatment": ExperimentVariant(
            id=uid("variant", "e3t"),
            experiment_id=e3.id,
            key="treatment",
            name="Curiosity-gap subject",
            weight=0.5,
            description="Implies a problem the reader has to open the email to resolve, with no value claim.",
        ),
    }
    for vs in c.variants.values():
        c.db.add_all(vs.values())


# --------------------------------------------------------------------------------------------------
# Accounts, contacts, signals
# --------------------------------------------------------------------------------------------------


def _account_from_profile(c: Ctx, p: CompanyProfile) -> Account:
    rng = c.rng
    created = c.d(-rng.uniform(190, 420))
    a = Account(
        id=uid("account", p.domain),
        workspace_id=c.ws.id,
        name=p.name,
        domain=p.domain,
        description=p.description,
        industry=p.industry,
        employee_count=p.employee_count,
        employee_growth_12m=p.employee_growth_12m,
        annual_revenue_usd=p.annual_revenue_usd,
        founded_year=p.founded_year,
        country=p.country,
        region=p.region,
        city=p.city,
        funding_stage=p.funding_stage,
        total_funding_usd=p.total_funding_usd,
        technologies=list(p.technologies),
        ai_team_size=p.ai_team_size,
        ai_open_roles=p.ai_open_roles,
        linkedin_url=f"https://www.linkedin.example/company/{p.domain.split('.')[0]}",
        segment=segment_for(p.employee_count),
        funnel_stage="prospect",
        lifecycle_stage="lead",
        source=rng.choice(["demo_seed:list_import", "demo_seed:clay_table", "demo_seed:crm_backfill"]),
        data_origin="demo",
        is_flagship=p is FLAGSHIP,
        created_at=created,
        updated_at=created,
    )
    # Realistic CRM gaps that enrichment can fill (the simulated providers know the true values).
    if p is not FLAGSHIP:
        if rng.random() < 0.12:
            a.technologies = list(p.technologies[: max(1, len(p.technologies) // 3)])  # stale partial stack
        if rng.random() < 0.08:
            a.ai_team_size = None
        if rng.random() < 0.05:
            a.industry = None
        if rng.random() < 0.3:
            a.hubspot_company_id = str(rng.randint(10**9, 10**10))
    r = rng.random()
    if p is FLAGSHIP:
        a.last_enriched_at = c.d(-9)
    elif r < 0.62:
        a.last_enriched_at = c.d(-rng.uniform(1, 170))
    elif r < 0.9:
        a.last_enriched_at = c.d(-rng.uniform(190, 400))
    return a


def _provenance(c: Ctx, a: Account, rows: list[dict[str, Any]]) -> None:
    for f in ("industry", "employee_count", "technologies", "funding_stage", "ai_team_size", "city", "country"):
        v = getattr(a, f)
        if v in (None, []):
            continue
        src = (
            c.rng.choice(["demo_firmographics", "demo_webscan", "crm_import"]) if f != "ai_team_size" else "demo_hiring"
        )
        if f == "technologies":
            src = "demo_webscan"
        rows.append(
            {
                "id": uid("prov", f"{a.id}:{f}"),
                "workspace_id": c.ws.id,
                "entity_type": "account",
                "entity_id": a.id,
                "field": f,
                "value": v,
                "source": src,
                "confidence": round(c.rng.uniform(0.62, 0.94), 2),
                "observed_at": a.last_enriched_at or a.created_at,
                "is_manual_lock": False,
            }
        )


def _pick_titles(c: Ctx, n: int, maturity: float) -> list[tuple[str, str, str]]:
    chosen: list[tuple[str, str, str]] = []
    pool = list(TITLES)
    for _ in range(n):
        total = sum(w * (1.4 if dept == "ai_ml" and maturity > 0.5 else 1.0) for _, _, dept, w in pool)
        x = c.rng.random() * total
        acc = 0.0
        for item in pool:
            acc += item[3] * (1.4 if item[2] == "ai_ml" and maturity > 0.5 else 1.0)
            if x < acc:
                chosen.append((item[0], item[1], item[2]))
                if item[1] in ("c_suite", "vp") or c.rng.random() < 0.6:
                    pool.remove(item)
                break
    return chosen


def _contacts(c: Ctx, a: Account, p: CompanyProfile) -> None:
    n = min(3 + int(math.log10(max(p.employee_count, 10)) * 1.3) + c.rng.randint(-1, 1), 9)
    used: set[str] = set()
    for title, seniority, dept in _pick_titles(c, max(n, 2), p.ai_maturity):
        for _ in range(10):
            first, last = c.rng.choice(FIRST), c.rng.choice(LAST)
            if f"{first}{last}" not in used:
                used.add(f"{first}{last}")
                break
        r = c.rng.random()
        status = "valid" if r < 0.87 else ("risky" if r < 0.935 else ("unknown" if r < 0.995 else "invalid"))
        ct = Contact(
            id=uid("contact", f"{a.domain}:{first}.{last}"),
            workspace_id=c.ws.id,
            account_id=a.id,
            first_name=first,
            last_name=last,
            email=f"{first}.{last}@{p.domain}".lower(),
            email_status=status,
            title=title,
            seniority=seniority,
            department=dept,
            persona=title,
            linkedin_url=f"https://www.linkedin.example/in/{first}-{last}".lower(),
            country=p.country,
            lifecycle_stage="lead",
            source="demo_seed",
            data_origin="demo",
            created_at=a.created_at + timedelta(days=c.rng.uniform(0, 30)),
        )
        c.contacts[a.id].append(ct)


def _signal(
    c: Ctx,
    a: Account,
    stype: str,
    days: float,
    title: str,
    explanation: str,
    *,
    confidence: float = 0.9,
    strength: float | None = None,
    source: str = "demo_signal_feed",
    evidence: dict[str, Any] | None = None,
    contact_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    observed = c.d(days)
    ref = f"{stype}:{title}:{observed.isoformat()}"
    row = {
        "id": uid("signal", f"{a.id}:{ref}"),
        "workspace_id": c.ws.id,
        "account_id": a.id,
        "contact_id": contact_id,
        "signal_type": stype,
        "observed_at": observed,
        "ingested_at": observed + timedelta(hours=c.rng.uniform(0.2, 20)),
        "source": source,
        "source_url": None,
        "confidence": confidence,
        "strength": strength if strength is not None else SIGNAL_TYPES[stype].default_strength,
        "title": title,
        "explanation": explanation,
        "evidence": evidence or {},
        "data_origin": "demo",
        "dedupe_key": signal_dedupe_key(stype, a.domain or str(a.id), ref),
    }
    c.signal_rows.append(row)
    c.signals[a.id].append(row)
    return row


def _recent(rng: random.Random, span: float, lo: float = 1.0, skew: float = 1.6) -> float:
    """A negative day offset skewed toward the recent past (signals cluster around active periods)."""
    return -max(lo, span * float(rng.random() ** skew))


def _signals_for(c: Ctx, a: Account, p: CompanyProfile) -> None:
    rng, m = c.rng, p.ai_maturity
    # Buying windows: at AI-mature companies signals cluster (a round funds hiring and a launch). A slice
    # of accounts is in an active window, which is exactly what signal-based selling tries to catch.
    hot = m > 0.55 and rng.random() < 0.16
    window = -rng.uniform(2, 28)

    def when(span: float, skew: float = 1.6) -> float:
        return min(-0.5, window + rng.uniform(-6, 3)) if hot and rng.random() < 0.85 else _recent(rng, span, skew=skew)

    if p.funding_stage in ("Seed", "Series A", "Series B", "Series C", "Series D+") and rng.random() < (
        0.7 if hot else 0.14 + 0.22 * m
    ):
        stage = {"Seed": "Series A", "Series A": "Series B"}.get(p.funding_stage, p.funding_stage)
        stage = "Series D" if stage == "Series D+" else stage
        amount = int(
            {
                "Series A": rng.uniform(8, 25),
                "Series B": rng.uniform(20, 60),
                "Series C": rng.uniform(50, 140),
                "Series D": rng.uniform(90, 250),
            }[stage]
        )
        days = when(175, 1.2)
        inv = rng.choice(INVESTORS)
        _signal(
            c,
            a,
            "funding_round",
            days,
            f"Raised ${amount}M {stage}",
            f"{a.name} raised a ${amount}M {stage} led by {inv} (fictional investor, DEMO feed).",
            confidence=round(rng.uniform(0.88, 0.98), 2),
            evidence={
                "round": stage,
                "amount_usd": amount * 1_000_000,
                "lead_investor": inv,
                "short": f"raised a ${amount}M {stage}",
                "hook": f"Your {stage}",
            },
        )
        a.last_funding_at = c.d(days).date()
        a.last_funding_amount_usd = amount * 1_000_000
    if p.ai_open_roles >= 4 and rng.random() < (0.9 if hot else 0.6):
        growth = int(rng.uniform(30, 180))
        _signal(
            c,
            a,
            "ai_hiring_surge",
            when(80),
            f"{p.ai_open_roles} open AI/ML roles",
            f"{p.ai_open_roles} open AI/ML engineering roles, up {growth}% in 60 days (DEMO job-postings index).",
            confidence=0.9,
            strength=min(0.95, 0.6 + p.ai_open_roles / 60),
            evidence={
                "open_roles": p.ai_open_roles,
                "growth_pct": growth,
                "short": f"is hiring {p.ai_open_roles} AI/ML engineers",
                "hook": "Scaling your AI team",
            },
        )
    if rng.random() < (0.7 if hot else 0.38 * m):
        job = rng.choice(JOB_POSTINGS)
        _signal(
            c,
            a,
            "job_posting",
            when(60),
            f"Posted: {job}",
            f"Job posting '{job}' mentions evaluation and reliability of LLM systems (DEMO).",
            confidence=0.85,
            evidence={"object": f"a '{job}' role", "short": f"is hiring a {job}", "hook": job},
        )
    if rng.random() < (0.6 if hot else 0.36 * m):
        prod = f"{a.name.split()[0]} {rng.choice(PRODUCT_WORDS)}"
        _signal(
            c,
            a,
            "ai_product_launch",
            when(120),
            f"Launched {prod}",
            f"{a.name} launched {prod}, an LLM-powered feature for customers (DEMO news feed).",
            confidence=round(rng.uniform(0.8, 0.95), 2),
            evidence={"object": prod, "short": f"launched {prod}", "hook": prod},
        )
    llm = [
        t
        for t in p.technologies
        if t in ("LangChain", "LlamaIndex", "Pinecone", "Weaviate", "vLLM", "Anthropic", "OpenAI")
    ]
    if llm and rng.random() < 0.35:
        t = rng.choice(llm)
        _signal(
            c,
            a,
            "tech_adoption",
            -rng.uniform(5, 170),
            f"Adopted {t}",
            f"Technographic scan detected {t} in {a.name}'s stack (DEMO).",
            confidence=0.75,
            evidence={"object": t, "short": f"adopted {t}", "hook": t},
        )
    if rng.random() < 0.1 + 0.05 * m:
        first, last = rng.choice(FIRST), rng.choice(LAST)
        title = rng.choice(EXEC_TITLES)
        _signal(
            c,
            a,
            "executive_hire",
            -rng.uniform(5, 150),
            f"Hired {first} {last} as {title}",
            f"{first} {last} joined {a.name} as {title} (DEMO people-movement feed).",
            confidence=0.88,
            evidence={
                "person": f"{first} {last}",
                "title": title,
                "short": f"brought on {first} {last} as {title}",
                "hook": f"Your new {title}",
            },
        )
    if rng.random() < 0.07:
        city = rng.choice(REGION_OFFICES.get(p.region, ["London"]))
        _signal(
            c,
            a,
            "expansion",
            -rng.uniform(5, 150),
            f"Opened {city} office",
            f"{a.name} announced a new office in {city} (DEMO).",
            confidence=0.8,
            evidence={"short": f"opened an office in {city}", "hook": city},
        )
    if rng.random() < 0.18:
        for _ in range(rng.randint(1, 3)):
            _signal(
                c,
                a,
                "website_visit",
                -rng.uniform(0, 60),
                "Visited docs and blog",
                "Reverse-IP matched visits to documentation and blog posts about agent evaluation (DEMO).",
                confidence=0.6,
                source="demo_web_analytics",
            )

    _negative_signals(c, a, p)


# Roughly the rate at which bad news actually shows up in a B2B list over a year. Deliberately not
# rare: a taxonomy whose disqualifying half never fires is a taxonomy nobody checks.
NEGATIVE_RATES: tuple[tuple[str, float], ...] = (
    ("competitor_adopted", 0.05),
    ("layoffs", 0.04),
    ("budget_freeze", 0.035),
    ("champion_departed", 0.03),
    ("ai_project_cancelled", 0.02),
    ("unsubscribed", 0.015),
)


def _negative_signals(c: Ctx, a: Account, p: CompanyProfile) -> None:
    """Disqualifying signals, so the demo can show the score arguing against an account.

    Correlated with maturity in the direction you would expect: a company with no AI programme cannot
    cancel one, and a competitor displaces you where there is something to displace.
    """
    rng = c.rng
    if a.is_flagship:
        return  # the flagship's story is a clean win; bad news there would muddle the walkthrough
    for stype, base in NEGATIVE_RATES:
        rate = base
        if stype in ("competitor_adopted", "ai_project_cancelled"):
            rate *= 0.4 + 1.2 * p.ai_maturity
        if rng.random() >= rate:
            continue
        days = -rng.uniform(5, 150)
        title, explanation, confidence = {
            "competitor_adopted": (
                "Competitor platform adopted",
                "Engineering blog and a conference talk describe a competing evaluation platform in production (DEMO).",
                0.8,
            ),
            "layoffs": (
                "Layoffs announced",
                "Public reporting of a workforce reduction affecting engineering (DEMO).",
                0.85,
            ),
            "budget_freeze": (
                "Hiring and spending freeze",
                "Leadership communication reported a freeze on new vendor spend this quarter (DEMO).",
                0.7,
            ),
            "champion_departed": (
                "Champion left the company",
                "The contact driving the evaluation updated their profile to a new employer (DEMO).",
                0.9,
            ),
            "ai_project_cancelled": (
                "AI initiative shelved",
                "The programme our product supports was publicly paused (DEMO).",
                0.75,
            ),
            "unsubscribed": (
                "Asked not to be contacted",
                "A contact used the unsubscribe link. Treated as account-level suppression (DEMO).",
                1.0,
            ),
        }[stype]
        _signal(c, a, stype, days, title, explanation, confidence=confidence, source="demo_signal_feed")


def _plg(
    c: Ctx, a: Account, p: CompanyProfile, *, force: dict[str, float] | None = None, user: Contact | None = None
) -> None:
    """Free-workspace product usage → engagement rows + product signals (PostHog-shaped)."""
    rng = c.rng
    contacts = sorted(
        (x for x in c.contacts[a.id] if x.department in ("ai_ml", "data", "engineering")),
        key=lambda x: (x.department != "ai_ml", x.seniority in ("c_suite", "vp"), str(x.id)),
    )
    if not contacts:
        return
    user = user or contacts[0]
    contacts = [user, *[x for x in contacts if x.id != user.id]]
    f = force or {}
    signup = f.get("signup", -rng.uniform(8, 115))

    def ev(name: str, days: float, props: dict[str, Any] | None = None, who: Contact | None = None) -> None:
        who = who or user
        k = c.key("eng")  # deterministic sequence number
        c.engagement_rows.append(
            {
                "id": uid("eng", k),
                "workspace_id": c.ws.id,
                "account_id": a.id,
                "contact_id": who.id,
                "event_name": name,
                "distinct_id": who.email,
                "occurred_at": c.d(days),
                "properties": {"$groups": {"company": a.domain}, **(props or {})},
                "source": "demo_seed",
                "data_origin": "demo",
                "dedupe_key": f"demo:{k}",
            }
        )

    ev("workspace_created", signup, {"plan": "free"})
    _signal(
        c,
        a,
        "product_signup",
        signup,
        "Created a free Sentinel workspace",
        f"{user.full_name} ({user.title}) created a free workspace (product event 'workspace_created').",
        confidence=0.97,
        source="posthog",
        contact_id=user.id,
        evidence={
            "event": "workspace_created",
            "short": "started using Sentinel's free workspace",
            "hook": "Your Sentinel workspace",
        },
    )
    day = signup
    while day < -0.5:
        day += rng.uniform(0.7, 4)
        if day < 0:
            ev("trace_logged", day, {"traces": int(rng.uniform(200, 5000))})
    if "invite" in f or rng.random() < 0.6:
        d = f.get("invite", signup + rng.uniform(1, 12))
        if d < 0:
            others = list(contacts[1:3]) or [user]
            for o in others:
                ev("teammate_invited", d, {"invitee": o.email})
            _signal(
                c,
                a,
                "teammate_invited",
                d,
                "Invited teammates to the free workspace",
                f"{user.full_name} invited {len(others)} teammate(s).",
                confidence=0.97,
                source="posthog",
                contact_id=user.id,
                evidence={"event": "teammate_invited", "count": len(others)},
            )
    integ = "integration" in f or rng.random() < 0.5
    if integ:
        d = f.get("integration", signup + rng.uniform(2, 20))
        if d < 0:
            ev("integration_connected", d, {"integration": rng.choice(["openai", "anthropic", "langchain"])})
            _signal(
                c,
                a,
                "integration_activated",
                d,
                "Connected a production integration",
                "Connected the tracing SDK to a production model provider.",
                confidence=0.97,
                source="posthog",
                contact_id=user.id,
                evidence={"event": "integration_connected"},
            )
    if "pricing" in f or rng.random() < 0.45:
        d = f.get("pricing", -rng.uniform(1, 40))
        views = rng.randint(2, 4)
        for i in range(views):
            ev("pricing_page_viewed", d - i * 0.6, {"$pathname": "/pricing"})
        _signal(
            c,
            a,
            "pricing_page_visit",
            d,
            f"Viewed pricing {views} times in 7 days",
            f"{views} pricing-page views from {user.full_name}'s workspace in one week.",
            confidence=0.95,
            source="posthog",
            contact_id=user.id,
            evidence={"views": views},
        )
    if "threshold" in f or (integ and rng.random() < 0.45):
        d = f.get("threshold", -rng.uniform(1, 30))
        ev("trace_volume_threshold", d, {"traces_30d": 250_000})
        _signal(
            c,
            a,
            "usage_threshold",
            d,
            "Crossed the free-tier trace volume threshold",
            "250,000 traces in 30 days: above the free-tier limit (product-qualified account).",
            confidence=0.98,
            source="posthog",
            contact_id=user.id,
            evidence={
                "event": "trace_volume_threshold",
                "short": "is already running production traffic through Sentinel's free tier",
                "hook": "Your Sentinel usage",
            },
        )


# --------------------------------------------------------------------------------------------------
# Journeys: outreach → replies → meetings → opportunities
# --------------------------------------------------------------------------------------------------


def _activity(
    c: Ctx,
    a: Account,
    typ: str,
    days: float,
    *,
    contact: Contact | None = None,
    campaign: str | None = None,
    step: SequenceStep | None = None,
    channel: str | None = "email",
    subject: str | None = None,
    summary: str | None = None,
    user_id: uuid.UUID | None = None,
    props: dict[str, Any] | None = None,
    draft_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    row = {
        "id": uid("activity", c.key("act")),
        "workspace_id": c.ws.id,
        "account_id": a.id,
        "contact_id": contact.id if contact else None,
        "user_id": user_id or a.owner_id,
        "type": typ,
        "channel": channel,
        "occurred_at": c.d(days),
        "campaign_id": c.campaigns[campaign].id if campaign else None,
        "sequence_step_id": step.id if step else None,
        "message_draft_id": draft_id,
        "subject": subject,
        "summary": summary,
        "status": None,
        "properties": props or {},
        "source": "demo_seed",
        "data_origin": "demo",
        "dedupe_key": None,
    }
    c.activity_rows.append(row)
    return row


def _transition(c: Ctx, a: Account, to: str, days: float, reason: str, by: str = "system") -> None:
    c.transition_rows.append(
        {
            "id": uid("transition", c.key("tr")),
            "workspace_id": c.ws.id,
            "entity_type": "account",
            "entity_id": a.id,
            "pipeline": "funnel",
            "from_stage": a.funnel_stage if a.funnel_stage != to else None,
            "to_stage": to,
            "changed_at": c.d(days),
            "changed_by": by,
            "reason": reason,
        }
    )
    a.funnel_stage = to
    lc = FUNNEL_TO_LIFECYCLE.get(to)
    if lc:
        a.lifecycle_stage = lc


def _propensity(p: CompanyProfile, a: Account) -> float:
    core = {"AI/ML Platforms": 1.0, "Developer Tools": 0.9, "Data Infrastructure": 0.9, "B2B SaaS": 0.75}
    fit = core.get(p.industry, 0.4)
    size = 1.0 if 250 <= p.employee_count <= 5000 else (0.7 if 100 <= p.employee_count <= 10000 else 0.35)
    return max(0.02, min(1.0, 0.45 * p.ai_maturity + 0.3 * fit + 0.25 * size))


# Campaigns whose first step is AI-personalised per account. Template-only motions (the generic ICP campaign
# and the funding-trigger control arm) send the sequence template, so they have a sequence step but no draft.
PERSONALISED_CAMPAIGNS = {"agent-launch", "plg-to-prod"}
ANGLE_SIGNAL_TYPES = {spec[1] for spec in ANGLES.values()}
SENDER_NAME = "Jordan Lee, Sentinel AI"


def _historical_draft(c: Ctx, a: Account, contact: Contact, camp: str, when: float, approver: User) -> uuid.UUID | None:
    """Recreate the approved draft that produced a historical send, using the real personalization engine.

    Seeded history is demo data, but it is produced by the same code path the live product uses, so the
    lineage (evidence → draft → guardrails → approval → send) is genuine rather than decorative.
    """
    sigs = sorted(c.signals[a.id], key=lambda s: s["observed_at"], reverse=True)
    anchor = next((s for s in sigs if s["signal_type"] in ANGLE_SIGNAL_TYPES), None)
    if anchor is None:
        return None
    angle = next(k for k, v in ANGLES.items() if v[1] == anchor["signal_type"])
    ev = [{"ref": "E1", "label": anchor["title"], "detail": anchor["explanation"]}]
    inp = PersonalizationInput(
        account={"name": a.name},
        contact={
            "first_name": contact.first_name,
            "name": contact.full_name,
            "title": contact.title,
            "email_status": contact.email_status,
            "do_not_contact": contact.do_not_contact,
        },
        angle=angle,
        anchor_signal={
            "id": str(anchor["id"]),
            "title": anchor["title"],
            "short": (anchor["evidence"] or {}).get("short") or anchor["title"].lower(),
            "subject_hook": (anchor["evidence"] or {}).get("hook") or a.name,
            "confidence": anchor["confidence"],
            "observed_at": anchor["observed_at"],
            "ref": "E1",
        },
        evidence=ev,
        sender_name=SENDER_NAME,
        now=c.d(when),
    )
    email = next((d for d in generate_messages(inp) if d.channel == "email"), None)
    if email is None or email.blocked:
        return None
    draft_id = uid("draft", f"{a.id}:{contact.id}:{camp}")
    c.draft_rows.append(
        {
            "id": draft_id,
            "workspace_id": c.ws.id,
            "account_id": a.id,
            "contact_id": contact.id,
            "campaign_id": c.campaigns[camp].id,
            "research_report_id": None,
            "channel": "email",
            "subject": email.subject,
            "body": email.body,
            "angle": email.angle,
            "reasoning_chain": jsonable(email.chain),
            "evidence": ev,
            "guardrails": email.guardrails_json(),
            "status": "ready",
            "generator": "demo-deterministic",
            "version": 1,
            "reviewed_by": approver.email,
            "approved_by": approver.email,
            "approved_at": c.d(when - 0.2),
            "rejection_reason": None,
            "workflow_run_id": None,
            "created_at": c.d(when - 0.5),
            "updated_at": c.d(when - 0.2),
        }
    )
    return draft_id


def _outcome(
    c: Ctx, exp_unit: dict[str, Any], metric: str, at: float, value: float = 1.0, note: str | None = None
) -> None:
    c.outcome_rows.append(
        {
            "id": uid("outcome", f"{exp_unit['id']}:{metric}"),
            "assignment_id": exp_unit["id"],
            "metric": metric,
            "value": value,
            "occurred_at": c.d(at),
            "source_activity_id": None,
            "note": note,
        }
    )


def _guardrail_outcomes(
    c: Ctx, a: Account, exp_unit: dict[str, Any], arm: str, enroll: float, bounced_at: float | None
) -> None:
    """Bounce, unsubscribe and spam-complaint outcomes for one assigned account.

    The bounce mirrors a real simulated bounce event; the other two have no activity of their own and are
    drawn from a generator seeded off the account id. That keeps them reproducible in isolation and leaves
    the run-wide RNG stream untouched, so adding guardrails moved no other number in the dataset.
    """
    if bounced_at is not None:
        _outcome(c, exp_unit, "bounce", bounced_at, note="first send to the primary contact hard-bounced")
    unsub_p, spam_p = GUARDRAIL_RATES[arm]
    g = random.Random(uid("guardrail", str(a.id)).int)
    if g.random() < unsub_p:
        _outcome(c, exp_unit, "unsubscribe", min(enroll + g.uniform(0.2, 9.0), -0.5))
    if g.random() < spam_p:
        _outcome(c, exp_unit, "spam_complaint", min(enroll + g.uniform(0.2, 9.0), -0.5))


# How much each disqualifying signal reduces the chance this account engages at all. Severity mirrors
# the score penalties: an unsubscribe is close to fatal, a budget freeze is a delay.
NEGATIVE_DRAG: dict[str, float] = {
    "unsubscribed": 0.05,
    "competitor_adopted": 0.35,
    "ai_project_cancelled": 0.4,
    "champion_departed": 0.55,
    "budget_freeze": 0.6,
    "layoffs": 0.65,
}


def _negative_drag(signals: list[dict[str, Any]]) -> float:
    drag = 1.0
    for s in signals:
        drag *= NEGATIVE_DRAG.get(s["signal_type"], 1.0)
    return max(drag, 0.02)


def _journey(c: Ctx, a: Account, p: CompanyProfile) -> None:
    rng = c.rng
    sigs = c.signals[a.id]
    prop = _propensity(p, a)
    if a.region in ("APAC", "LATAM"):
        prop *= 0.9
    # A disqualifying signal has to actually disqualify. Subtracting points from the score without
    # making the simulated world respond would add pure noise to the ranking: the backtest would then
    # show the score getting *worse* for modelling risk correctly, which is an artefact of the seed
    # rather than a property of the score. Applied as a multiplier on the existing propensity so no
    # extra RNG is drawn and the rest of the dataset is unchanged.
    prop *= _negative_drag(sigs)
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in sigs:
        by_type[s["signal_type"]].append(s)
    enroll: float | None = None
    camp = None

    def days_of(s: dict[str, Any]) -> float:
        return float((s["observed_at"] - c.anchor).total_seconds() / 86400)

    fund = [s for s in by_type["funding_round"] if -170 <= days_of(s) <= -45]
    launch = [s for s in by_type["ai_product_launch"] if days_of(s) >= -95]
    signup = by_type["product_signup"]
    # The funding campaign targets every account with a round in its window; other motions are selective.
    if not fund and rng.random() > 0.2 + 0.6 * prop:
        return
    if fund:
        camp, enroll = "funding-trigger", min(days_of(fund[0]) + rng.uniform(2, 7), -38)
    elif launch and days_of(launch[0]) < -3:
        camp, enroll = "agent-launch", days_of(launch[0]) + rng.uniform(1, 6)
    elif signup and days_of(signup[0]) < -4:
        camp, enroll = "plg-to-prod", days_of(signup[0]) + rng.uniform(1, 4)
    elif a.region == "EMEA" and rng.random() < 0.5:
        camp, enroll = "emea-ai-infra", -rng.uniform(4, 110)
    else:
        camp, enroll = "icp-generic", -rng.uniform(4, 180)
    enroll = min(enroll, -1.0)

    variant_key = None
    if camp == "funding-trigger":
        variant_key, bucket = assign_variant("exp-funding-v1", str(a.id), [("control", 0.5), ("treatment", 0.5)])
        var = c.variants["funding-vs-generic"][variant_key]
        c.assignment_rows.append(
            {
                "id": uid("assign", f"e1:{a.id}"),
                "experiment_id": var.experiment_id,
                "variant_id": var.id,
                "unit_id": a.id,
                "account_id": a.id,
                "assigned_at": c.d(enroll),
                "exposed_at": c.d(enroll),
                "bucket": bucket,
            }
        )
    elif camp == "agent-launch" and enroll >= -21:
        variant_key, bucket = assign_variant("exp-subject-v1", str(a.id), [("control", 0.5), ("treatment", 0.5)])
        var = c.variants["subject-question"][variant_key]
        c.assignment_rows.append(
            {
                "id": uid("assign", f"e2:{a.id}"),
                "experiment_id": var.experiment_id,
                "variant_id": var.id,
                "unit_id": a.id,
                "account_id": a.id,
                "assigned_at": c.d(enroll),
                "exposed_at": c.d(enroll),
                "bucket": bucket,
            }
        )
    elif camp == "icp-generic":
        variant_key, bucket = assign_variant("exp-provocative-v1", str(a.id), [("control", 0.5), ("treatment", 0.5)])
        var = c.variants["provocative-subject"][variant_key]
        c.assignment_rows.append(
            {
                "id": uid("assign", f"e3:{a.id}"),
                "experiment_id": var.experiment_id,
                "variant_id": var.id,
                "unit_id": a.id,
                "account_id": a.id,
                "assigned_at": c.d(enroll),
                "exposed_at": c.d(enroll),
                "bucket": bucket,
            }
        )
    exp_key = {
        "funding-trigger": "funding-vs-generic",
        "agent-launch": "subject-question",
        "icp-generic": "provocative-subject",
    }.get(camp)
    arm = f"{exp_key}:{variant_key}" if variant_key else None

    targets = sorted(
        c.contacts[a.id],
        key=lambda x: (x.department != "ai_ml", x.seniority not in ("director", "vp", "manager"), str(x.id)),
    )
    targets = [t for t in targets if t.department in ("ai_ml", "engineering", "data")][: rng.randint(1, 3)]
    if not targets:
        return
    step_key = f"{camp}:{variant_key}" if camp == "funding-trigger" else camp
    steps = c.steps[step_key]

    # Earlier nurture touch for roughly a third of accounts, so journeys are genuinely multi-touch and the
    # attribution models have something to disagree about (first touch ≠ last touch).
    first_touch = enroll
    if rng.random() < 0.35:
        if camp != "icp-generic":
            prior_at = enroll - rng.uniform(25, 100)
            if prior_at > -178:
                first_touch = prior_at
                for t in targets[:1]:
                    _activity(
                        c,
                        a,
                        "email_sent",
                        prior_at,
                        contact=t,
                        campaign="icp-generic",
                        step=c.steps["icp-generic"][0],
                        subject=f"{a.name}: evaluating LLM agents",
                    )
                    _activity(
                        c,
                        a,
                        "email_delivered",
                        prior_at + 0.001,
                        contact=t,
                        campaign="icp-generic",
                        step=c.steps["icp-generic"][0],
                    )
        elif enroll > -96:
            first_touch = -100.0
            for t in targets[:1]:
                _activity(
                    c,
                    a,
                    "webinar_attended",
                    -100.0,
                    contact=t,
                    campaign="webinar-agents",
                    channel="event",
                    subject="Webinar: Evaluating LLM agents in production",
                )
    _transition(c, a, "contacted", first_touch, f"First touch; later enrolled in '{c.campaigns[camp].name}'")

    approver = c.users["riley"]
    personalised = camp in PERSONALISED_CAMPAIGNS or (camp == "funding-trigger" and variant_key == "treatment")
    drafts_by_contact: dict[uuid.UUID, uuid.UUID | None] = {}
    if personalised:
        for t in targets:
            drafts_by_contact[t.id] = _historical_draft(c, a, t, camp, enroll, approver)
    mult = REPLY_MULTIPLIER.get(f"{camp}:{variant_key}" if camp == "funding-trigger" else camp, 1.0)
    if camp == "agent-launch" and variant_key == "treatment":
        mult *= 1.1
    provocative = arm == "provocative-subject:treatment"  # only the subject line differs inside the journey
    reply_p = min(0.5, (0.045 + 0.12 * prop) * mult)
    replied_at: float | None = None
    replier: Contact | None = None
    positive = False
    bounced_at: float | None = None
    for t in targets:
        will_reply = rng.random() < reply_p
        reply_step = rng.randint(1, 3) if will_reply else 0
        for st in steps:
            d = enroll + st.delay_days + rng.uniform(0, 0.4)
            if d >= 0:
                break
            if replied_at is not None and d > replied_at:
                break
            subj = (st.subject_template or "").replace("{hook}", a.name)
            if provocative and st.step_number == 1:
                subj = f"Is {a.name}'s agent stack about to break?"
            _activity(
                c,
                a,
                "email_sent",
                d,
                contact=t,
                campaign=camp,
                step=st,
                subject=subj,
                draft_id=drafts_by_contact.get(t.id) if st.step_number == 1 else None,
            )
            if rng.random() < 0.97:
                _activity(c, a, "email_delivered", d + 0.001, contact=t, campaign=camp, step=st, subject=subj)
                if rng.random() < 0.42:
                    _activity(
                        c,
                        a,
                        "email_opened",
                        d + rng.uniform(0.01, 1.5),
                        contact=t,
                        campaign=camp,
                        step=st,
                        subject=subj,
                        props={"caveat": "open tracking unreliable (Apple MPP)"},
                    )
            else:
                _activity(c, a, "email_bounced", d + 0.001, contact=t, campaign=camp, step=st, subject=subj)
                # The guardrail counts the primary contact's first send only, so the experiment metric reads
                # as a per-address bounce rate rather than "any bad address anywhere at this account".
                if bounced_at is None and t is targets[0] and st.step_number == 1:
                    bounced_at = d + 0.001
                break
            if st.step_number == reply_step:
                rd = d + rng.uniform(0.1, 3)
                if rd < 0 and replied_at is None:
                    replied_at, replier = rd, t
                    positive = rng.random() < 0.42 + 0.3 * prop
                    _activity(
                        c,
                        a,
                        "email_replied",
                        rd,
                        contact=t,
                        campaign=camp,
                        step=st,
                        subject=f"Re: {subj}",
                        summary="Reply received",
                    )
                    if positive:
                        _activity(
                            c,
                            a,
                            "positive_reply",
                            rd + 0.001,
                            contact=t,
                            campaign=camp,
                            step=st,
                            subject=f"Re: {subj}",
                            summary="Interested: asked for time next week",
                        )
                break
    exp_unit = next((r for r in c.assignment_rows if r["unit_id"] == a.id), None)
    if exp_unit and arm:
        _guardrail_outcomes(c, a, exp_unit, arm, enroll, bounced_at)
    if replied_at is None or replier is None:
        return
    _transition(c, a, "engaged", replied_at, "Two-way engagement (reply)")
    if exp_unit:
        c.outcome_rows.append(
            {
                "id": uid("outcome", f"{exp_unit['id']}:reply"),
                "assignment_id": exp_unit["id"],
                "metric": "reply",
                "value": 1.0,
                "occurred_at": c.d(replied_at),
                "source_activity_id": None,
                "note": None,
            }
        )
    if not positive:
        if rng.random() < 0.3:
            _transition(c, a, "lost", replied_at + 0.01, "Replied: not interested")
            if exp_unit:
                _outcome(c, exp_unit, "negative_reply", replied_at + 0.01, note="explicit 'not interested' reply")
        return
    _transition(c, a, "qualified", replied_at + rng.uniform(0.5, 3), "Positive reply qualified on discovery screen")
    if exp_unit:
        c.outcome_rows.append(
            {
                "id": uid("outcome", f"{exp_unit['id']}:pos"),
                "assignment_id": exp_unit["id"],
                "metric": "positive_reply",
                "value": 1.0,
                "occurred_at": c.d(replied_at),
                "source_activity_id": None,
                "note": None,
            }
        )
    stuck = a.region in ("APAC", "LATAM")  # no routing rule → nobody books the meeting
    if rng.random() > (0.68 if not stuck else 0.12):
        return
    booked = replied_at + rng.uniform(0.5, 4)
    if booked >= 0:
        return
    _activity(
        c,
        a,
        "meeting_booked",
        booked,
        contact=replier,
        campaign=camp,
        channel="meeting",
        subject="Intro: Sentinel AI",
        summary="Discovery call booked",
    )
    held = booked + rng.uniform(2, 9)
    if held >= 0:
        return
    _activity(
        c,
        a,
        "meeting_held",
        held,
        contact=replier,
        campaign=camp,
        channel="meeting",
        subject="Discovery call",
        summary="Discussed agent reliability and evaluation workflow",
    )
    _transition(c, a, "meeting", held, "Discovery meeting held")
    if exp_unit:
        c.outcome_rows.append(
            {
                "id": uid("outcome", f"{exp_unit['id']}:mtg"),
                "assignment_id": exp_unit["id"],
                "metric": "meeting",
                "value": 1.0,
                "occurred_at": c.d(held),
                "source_activity_id": None,
                "note": None,
            }
        )
    if rng.random() > 0.42 + 0.42 * prop:
        return
    opened = held + rng.uniform(2, 12)
    if opened >= 0:
        return
    lo, hi = OPP_AMOUNT.get(a.segment or "mid_market", (30_000, 70_000))
    amount = round(rng.uniform(lo, hi) / 1000) * 1000
    _transition(c, a, "opportunity", opened, "Opportunity created after discovery")
    opp_id = uid("opp", str(a.id))
    stage, closed_at, lost_reason = rng.choice(["discovery", "evaluation", "evaluation", "proposal"]), None, None
    age = -opened
    if age > 40 and rng.random() < 0.7:
        close_d = opened + rng.uniform(30, min(age, 110))
        if close_d < 0:
            if rng.random() < 0.3 + 0.3 * prop:
                stage, closed_at = "closed_won", close_d
                _transition(c, a, "won", close_d, "Closed won")
                a.is_customer = True
            else:
                stage, closed_at = "closed_lost", close_d
                lost_reason = rng.choice(["No budget", "Built in-house", "Chose competitor", "Timing"])
                _transition(c, a, "lost", close_d, f"Closed lost: {lost_reason}")
    elif age > 25:
        stage = rng.choice(["evaluation", "proposal", "negotiation"])
    c.opp_rows.append(
        {
            "id": opp_id,
            "workspace_id": c.ws.id,
            "account_id": a.id,
            "name": f"{a.name}: Agent Reliability Platform",
            "stage": stage,
            "amount_usd": amount,
            "opened_at": c.d(opened),
            "expected_close_date": c.d(opened + 75).date(),
            "closed_at": c.d(closed_at) if closed_at is not None else None,
            "owner_id": None,
            "primary_contact_id": replier.id,
            "source_campaign_id": c.campaigns[camp].id,
            "lead_source": "plg" if camp == "plg-to-prod" else "outbound",
            "lost_reason": lost_reason,
            "data_origin": "demo",
            "created_at": c.d(opened),
            "updated_at": c.d(opened),
        }
    )
    if exp_unit:
        c.outcome_rows.append(
            {
                "id": uid("outcome", f"{exp_unit['id']}:opp"),
                "assignment_id": exp_unit["id"],
                "metric": "opportunity",
                "value": float(amount),
                "occurred_at": c.d(opened),
                "source_activity_id": None,
                "note": "value = opportunity amount (USD)",
            }
        )


def _provocative_arm_outcomes(c: Ctx) -> None:
    """Layer the curiosity-gap arm's extra replies onto the experiment, after every journey has run.

    The treatment wins the primary metric and most of that win is hostile: the rest is a brush-off. The same
    pass therefore produces both the lift and the negative-reply breach. It touches `experiment_outcomes`
    only: no funnel transition, no score, no activity, and no draw from the run-wide generator — the
    cautionary experiment must not be able to move a number anywhere else in the demo.
    """
    treatment = c.variants["provocative-subject"]["treatment"].id
    replied = {r["assignment_id"] for r in c.outcome_rows if r["metric"] == "reply"}
    for row in c.assignment_rows:
        if row["variant_id"] != treatment or row["id"] in replied:
            continue
        g = random.Random(uid("curiosity", str(row["unit_id"])).int)
        if g.random() >= CURIOSITY_EXTRA_REPLY_P:
            continue
        at = (row["assigned_at"] - c.anchor).total_seconds() / 86400 + g.uniform(0.5, 6.0)
        at = min(at, -0.5)
        _outcome(c, row, "reply", at, note="curiosity reply: opened by the subject, no interest in the offer")
        if g.random() < CURIOSITY_HOSTILE_SHARE:
            _outcome(c, row, "negative_reply", at + 0.01, note="told us to stop emailing")


def _inbound_opportunities(c: Ctx, candidates: list[Account]) -> None:
    """Inbound/referral deals with no recorded GTMOS touches.

    Every real attribution report has an unattributed tail: demo requests, referrals, events and conversations
    that never touch the system of record. Modelling it keeps the attribution page honest, and gives the
    'what share of pipeline can we even attribute?' conversation something to bite on.
    """
    rng = random.Random(RNG_SEED + 31)
    pool = [a for a in candidates if a.funnel_stage == "prospect" and not a.is_customer and a.domain]
    for a in rng.sample(pool, min(16, len(pool))):
        opened = -rng.uniform(5, 150)
        source = rng.choice(["inbound", "referral", "partner"])
        reason = {
            "inbound": "Inbound demo request (form fill logged in the CRM, no GTMOS touches)",
            "referral": "Referred by an existing customer; conversation happened over email outside GTMOS",
            "partner": "Partner-sourced introduction",
        }[source]
        for stage, dd in (
            ("qualified", opened - rng.uniform(6, 20)),
            ("meeting", opened - rng.uniform(2, 5)),
            ("opportunity", opened),
        ):
            _transition(c, a, stage, dd, reason, by="crm_manual")
        _activity(
            c,
            a,
            "note",
            opened - 0.5,
            channel=None,
            subject="Inbound request",
            summary=reason,
        )
        lo, hi = OPP_AMOUNT.get(a.segment or "mid_market", (30_000, 70_000))
        amount = round(rng.uniform(lo, hi) / 1000) * 1000
        stage, closed_at, lost_reason = "evaluation", None, None
        if -opened > 45 and rng.random() < 0.55:
            close_d = opened + rng.uniform(25, min(-opened, 90))
            if close_d < 0:
                if rng.random() < 0.45:
                    stage, closed_at = "closed_won", close_d
                    _transition(c, a, "won", close_d, "Closed won (inbound)")
                    a.is_customer = True
                else:
                    stage, closed_at = "closed_lost", close_d
                    lost_reason = rng.choice(["No budget", "Timing", "Chose competitor"])
                    _transition(c, a, "lost", close_d, f"Closed lost: {lost_reason}")
        c.opp_rows.append(
            {
                "id": uid("opp", f"inbound:{a.id}"),
                "workspace_id": c.ws.id,
                "account_id": a.id,
                "name": f"{a.name}: Agent Reliability Platform",
                "stage": stage,
                "amount_usd": amount,
                "opened_at": c.d(opened),
                "expected_close_date": c.d(opened + 60).date(),
                "closed_at": c.d(closed_at) if closed_at is not None else None,
                "owner_id": None,
                "primary_contact_id": None,
                "source_campaign_id": None,
                "lead_source": source,
                "lost_reason": lost_reason,
                "data_origin": "demo",
                "created_at": c.d(opened),
                "updated_at": c.d(opened),
            }
        )


def _webinar(c: Ctx, a: Account) -> None:
    attendees = [x for x in c.contacts[a.id] if x.department == "ai_ml"][:2]
    for t in attendees:
        _activity(
            c,
            a,
            "webinar_attended",
            -100 + c.rng.uniform(0, 0.1),
            contact=t,
            campaign="webinar-agents",
            channel="event",
            subject="Webinar: Evaluating LLM agents in production",
        )


def _customer(c: Ctx, a: Account) -> None:
    """Existing customer won before the analysis window."""
    won = -c.rng.uniform(220, 400)
    for stage, dd in (
        ("contacted", won - 90),
        ("engaged", won - 80),
        ("qualified", won - 75),
        ("meeting", won - 70),
        ("opportunity", won - 60),
        ("won", won),
    ):
        _transition(c, a, stage, dd, "Historical (pre-GTMOS CRM backfill)")
    a.is_customer = True
    a.lifecycle_stage = "customer"
    lo, hi = OPP_AMOUNT.get(a.segment or "mid_market", (30_000, 70_000))
    c.opp_rows.append(
        {
            "id": uid("opp", f"hist:{a.id}"),
            "workspace_id": c.ws.id,
            "account_id": a.id,
            "name": f"{a.name}: Initial platform deal",
            "stage": "closed_won",
            "amount_usd": round(c.rng.uniform(lo, hi) / 1000) * 1000,
            "opened_at": c.d(won - 60),
            "expected_close_date": c.d(won).date(),
            "closed_at": c.d(won),
            "owner_id": None,
            "primary_contact_id": None,
            "source_campaign_id": None,
            "lead_source": "inbound",
            "lost_reason": None,
            "data_origin": "demo",
            "created_at": c.d(won - 60),
            "updated_at": c.d(won),
        }
    )


# --------------------------------------------------------------------------------------------------
# Flagship
# --------------------------------------------------------------------------------------------------


def _flagship(c: Ctx, a: Account) -> None:
    people = [
        ("Dana", "Whitfield", "Chief Technology Officer", "c_suite", "engineering"),
        ("Marcus", "Chen", "VP Engineering", "vp", "engineering"),
        ("Elena", "Park", "VP of AI", "vp", "ai_ml"),
        ("Priya", "Raman", "Head of AI Platform", "director", "ai_ml"),
        ("Tomás", "Alvarez", "Staff ML Engineer, Platform", "ic", "ai_ml"),
        ("Aisha", "Okafor", "ML Engineer", "ic", "ai_ml"),
        ("Ben", "Castro", "VP Marketing", "vp", "marketing"),
    ]
    for first, last, title, sen, dept in people:
        email = f"{first.lower().replace('á', 'a')}.{last.lower()}@{a.domain}"
        c.contacts[a.id].append(
            Contact(
                id=uid("contact", f"{a.domain}:{first}.{last}"),
                workspace_id=c.ws.id,
                account_id=a.id,
                first_name=first,
                last_name=last,
                email=email,
                email_status="valid",
                title=title,
                seniority=sen,
                department=dept,
                persona=title,
                country="US",
                lifecycle_stage="lead",
                source="demo_seed",
                data_origin="demo",
                linkedin_url=f"https://www.linkedin.example/in/{first}-{last}".lower(),
                created_at=c.d(-60),
            )
        )
    # A duplicate record for the champion, created by a webinar list import: a DQ issue in the story.
    c.contacts[a.id].append(
        Contact(
            id=uid("contact", f"{a.domain}:priya.dup"),
            workspace_id=c.ws.id,
            account_id=a.id,
            first_name="Priya",
            last_name="Raman",
            email=f" Priya.Raman@{(a.domain or '').upper()}",
            email_status="unknown",
            title="Head of AI",
            seniority="director",
            department="ai_ml",
            lifecycle_stage="lead",
            source="demo_seed:webinar_list",
            data_origin="demo",
            created_at=c.d(-40),
        )
    )
    ct = {x.first_name: x for x in c.contacts[a.id] if x.email and not x.email.startswith(" ")}

    def S(*args: Any, **kw: Any) -> dict[str, Any]:
        return _signal(c, a, *args, **kw)

    S(
        "tech_adoption",
        -45,
        "Adopted LangChain + Pinecone",
        "Technographic scan detected LangChain and Pinecone (RAG/agent stack) at Kestrel Analytics (DEMO).",
        confidence=0.8,
        evidence={
            "object": "LangChain + Pinecone",
            "short": "adopted LangChain and Pinecone",
            "hook": "LangChain + Pinecone",
        },
    )
    S(
        "executive_hire",
        -30,
        "Hired Elena Park as VP of AI",
        "Elena Park joined Kestrel Analytics as VP of AI, previously leading applied ML (DEMO people feed).",
        confidence=0.92,
        evidence={
            "person": "Elena Park",
            "title": "VP of AI",
            "short": "brought on Elena Park as VP of AI",
            "hook": "Your new VP of AI",
        },
    )
    S(
        "ai_product_launch",
        -26,
        "Launched Kestrel Copilot",
        "Kestrel Analytics launched Kestrel Copilot, an AI agent that answers questions over customer revenue "
        "data (DEMO news feed).",
        confidence=0.93,
        strength=0.85,
        evidence={"object": "Kestrel Copilot", "short": "launched Kestrel Copilot", "hook": "Kestrel Copilot"},
    )
    S(
        "funding_round",
        -12,
        "Raised $120M Series C",
        "Kestrel Analytics raised a $120M Series C led by Harbor Ridge Ventures (fictional) to expand Kestrel "
        "Copilot and its AI team (DEMO news feed).",
        confidence=0.97,
        evidence={
            "round": "Series C",
            "amount_usd": 120_000_000,
            "lead_investor": "Harbor Ridge Ventures",
            "short": "raised a $120M Series C",
            "hook": "Your Series C",
        },
    )
    S(
        "job_posting",
        -9,
        "Posted: Staff Engineer, LLM Evaluation",
        "Job posting 'Staff Engineer, LLM Evaluation' asks for experience building eval harnesses and "
        "monitoring agent regressions (DEMO).",
        confidence=0.9,
        evidence={
            "object": "a Staff Engineer, LLM Evaluation role",
            "short": "is hiring a Staff Engineer for LLM Evaluation",
            "hook": "LLM Evaluation hire",
        },
    )
    S(
        "ai_hiring_surge",
        -6,
        "14 open AI/ML roles",
        "14 open AI/ML engineering roles, up 133% in 60 days (DEMO job-postings index).",
        confidence=0.92,
        strength=0.9,
        evidence={
            "open_roles": 14,
            "growth_pct": 133,
            "short": "is hiring 14 AI/ML engineers",
            "hook": "Scaling your AI team",
        },
    )
    a.last_funding_at = c.d(-12).date()
    a.last_funding_amount_usd = 120_000_000
    _plg(
        c,
        a,
        FLAGSHIP,
        force={"signup": -16, "invite": -11, "integration": -8, "pricing": -3, "threshold": -2},
        user=ct["Priya"],
    )
    # Journey: webinar → ICP nurture → launch-triggered campaign → reply → meeting → opportunity.
    # Three campaigns over 100 days is what makes the attribution models disagree on this account.
    priya, tomas = ct["Priya"], ct["Tomás"]
    steps = c.steps["agent-launch"]
    for person in (priya, tomas):
        _activity(
            c,
            a,
            "webinar_attended",
            -100 + (0.01 if person is tomas else 0),
            contact=person,
            campaign="webinar-agents",
            channel="event",
            subject="Webinar: Evaluating LLM agents in production",
            summary="Attended the live session and asked about eval datasets in the Q&A",
        )
    _transition(c, a, "contacted", -100, "First touch: attended the LLM agent evaluation webinar")
    for st, d in zip(c.steps["icp-generic"][:2], (-62, -59), strict=True):
        _activity(
            c,
            a,
            "email_sent",
            d,
            contact=priya,
            campaign="icp-generic",
            step=st,
            subject="Kestrel Analytics: evaluating LLM agents",
        )
        _activity(c, a, "email_delivered", d + 0.001, contact=priya, campaign="icp-generic", step=st)
    _activity(
        c,
        a,
        "email_opened",
        -61.5,
        contact=priya,
        campaign="icp-generic",
        step=c.steps["icp-generic"][0],
        props={"caveat": "open tracking unreliable (Apple MPP)"},
    )
    flagship_draft = _historical_draft(c, a, priya, "agent-launch", -22, c.users["riley"])
    variant_key, bucket = assign_variant("exp-subject-v1", str(a.id), [("control", 0.5), ("treatment", 0.5)])
    var = c.variants["subject-question"][variant_key]
    assignment_id = uid("assign", f"e2:{a.id}")
    c.assignment_rows.append(
        {
            "id": assignment_id,
            "experiment_id": var.experiment_id,
            "variant_id": var.id,
            "unit_id": a.id,
            "account_id": a.id,
            "assigned_at": c.d(-22),
            "exposed_at": c.d(-22),
            "bucket": bucket,
        }
    )
    for metric, at, value in (
        ("reply", -17, 1.0),
        ("positive_reply", -17, 1.0),
        ("meeting", -6, 1.0),
        ("opportunity", -4, 180_000.0),
    ):
        c.outcome_rows.append(
            {
                "id": uid("outcome", f"{assignment_id}:{metric}"),
                "assignment_id": assignment_id,
                "metric": metric,
                "value": value,
                "occurred_at": c.d(at),
                "source_activity_id": None,
                "note": "value = opportunity amount (USD)" if metric == "opportunity" else None,
            }
        )
    for st, d in zip(steps[:2], (-22, -19), strict=True):
        _activity(
            c,
            a,
            "email_sent",
            d,
            contact=priya,
            campaign="agent-launch",
            step=st,
            subject="Kestrel Copilot: agent reliability",
            draft_id=flagship_draft if st.step_number == 1 else None,
        )
        _activity(
            c,
            a,
            "email_delivered",
            d + 0.001,
            contact=priya,
            campaign="agent-launch",
            step=st,
            subject="Kestrel Copilot: agent reliability",
        )
    _activity(
        c,
        a,
        "email_replied",
        -17,
        contact=priya,
        campaign="agent-launch",
        step=steps[1],
        subject="Re: Kestrel Copilot: agent reliability",
        summary="Priya: 'Timely. We're seeing Copilot regressions after prompt changes.'",
    )
    _activity(
        c,
        a,
        "positive_reply",
        -17 + 0.001,
        contact=priya,
        campaign="agent-launch",
        step=steps[1],
        subject="Re: Kestrel Copilot: agent reliability",
        summary="Interested: asked for a call",
    )
    _transition(c, a, "engaged", -17, "Priya Raman replied")
    _transition(c, a, "qualified", -14, "Positive reply; pain confirmed (agent regressions)")
    _activity(
        c,
        a,
        "meeting_booked",
        -13,
        contact=priya,
        campaign="agent-launch",
        channel="meeting",
        subject="Kestrel x Sentinel: discovery",
    )
    _activity(
        c,
        a,
        "meeting_held",
        -6,
        contact=priya,
        campaign="agent-launch",
        channel="meeting",
        subject="Discovery call with Priya Raman and Tomás Alvarez",
        summary="Copilot regressions after prompt changes; no eval gate in CI; Tomás owns the platform.",
    )
    _activity(
        c,
        a,
        "meeting_held",
        -6 + 0.001,
        contact=tomas,
        campaign="agent-launch",
        channel="meeting",
        subject="Discovery call with Priya Raman and Tomás Alvarez",
    )
    _transition(c, a, "meeting", -6, "Discovery meeting held")
    _transition(c, a, "opportunity", -4, "Opportunity created after discovery")
    c.opp_rows.append(
        {
            "id": uid("opp", str(a.id)),
            "workspace_id": c.ws.id,
            "account_id": a.id,
            "name": "Kestrel Analytics: Agent Reliability Platform",
            "stage": "discovery",
            "amount_usd": 180_000,
            "opened_at": c.d(-4),
            "expected_close_date": c.d(70).date(),
            "closed_at": None,
            "owner_id": None,
            "primary_contact_id": priya.id,
            "source_campaign_id": c.campaigns["agent-launch"].id,
            "lead_source": "outbound",
            "lost_reason": None,
            "data_origin": "demo",
            "created_at": c.d(-4),
            "updated_at": c.d(-4),
        }
    )


# --------------------------------------------------------------------------------------------------
# Data-quality defects (deliberate, counted, documented)
# --------------------------------------------------------------------------------------------------


def _inject_defects(c: Ctx) -> dict[str, int]:
    rng = random.Random(RNG_SEED + 99)
    normal = [a for a in c.accounts if not a.is_flagship and a.domain]
    counts: dict[str, int] = defaultdict(int)
    picks = rng.sample(normal, 90)
    it = iter(picks)
    # Duplicate accounts: 4 by domain variant, 2 by name (no domain)
    for _ in range(4):
        src = next(it)
        dup = Account(
            id=uid("account", f"dup:{src.domain}"),
            workspace_id=c.ws.id,
            name=src.name.upper(),
            domain=f"WWW.{(src.domain or '').upper()}",
            industry=src.industry,
            country=src.country,
            region=src.region,
            segment=src.segment,
            source="demo_seed:csv_upload",
            data_origin="demo",
            created_at=c.d(-rng.uniform(20, 90)),
            technologies=[],
        )
        c.db.add(dup)
        counts["duplicate_account"] += 1
    for _ in range(2):
        src = next(it)
        dup = Account(
            id=uid("account", f"dupname:{src.domain}"),
            workspace_id=c.ws.id,
            name=f"{src.name}, Inc.",
            domain=None,
            industry=src.industry,
            source="demo_seed:event_badge_scan",
            data_origin="demo",
            created_at=c.d(-rng.uniform(20, 90)),
            technologies=[],
        )
        c.db.add(dup)
        counts["duplicate_account"] += 1
        counts["missing_domain"] += 1
    for _ in range(7):
        a = next(it)
        a.domain = None
        counts["missing_domain"] += 1
    for _ in range(31):
        a = next(it)
        a.employee_count = None
        a.segment = None
        counts["missing_employee_count"] += 1
    # Lifecycle conflicts (accounts)
    for _ in range(5):
        a = next(it)
        if not a.is_customer:
            a.lifecycle_stage = "customer"
            counts["lifecycle_conflict"] += 1
    # Invalid transitions: CRM migration imported customers straight to 'won'
    for _ in range(5):
        a = next(it)
        if a.funnel_stage == "prospect" and not a.is_customer:
            c.transition_rows.append(
                {
                    "id": uid("transition", f"bad:{a.id}"),
                    "workspace_id": c.ws.id,
                    "entity_type": "account",
                    "entity_id": a.id,
                    "pipeline": "funnel",
                    "from_stage": "prospect",
                    "to_stage": "won",
                    "changed_at": c.d(-rng.uniform(150, 300)),
                    "changed_by": "crm_migration",
                    "reason": "Imported from legacy CRM",
                }
            )
            a.funnel_stage = "won"
            a.is_customer = True
            a.lifecycle_stage = "customer"
            counts["invalid_pipeline_transition"] += 1
    # Bad external ids: 4 malformed, 2 shared pairs
    for bad in ("N/A", "12-34", "hs_8841", "TBD"):
        next(it).hubspot_company_id = bad
        counts["bad_external_id"] += 1
    for _ in range(2):
        x, y = next(it), next(it)
        shared = str(rng.randint(10**9, 10**10))
        x.hubspot_company_id = shared
        y.hubspot_company_id = shared
        counts["bad_external_id"] += 1
    # Contact-level defects
    all_contacts = [ct for a in c.accounts if not a.is_flagship for ct in c.contacts[a.id]]
    cpicks = rng.sample(all_contacts, 80)
    cit = iter(cpicks)
    for _ in range(12):  # same email, different case/whitespace
        csrc = next(cit)
        acct = next(a for a in c.accounts if a.id == csrc.account_id)
        c.contacts[acct.id].append(
            Contact(
                id=uid("contact", f"dup:{csrc.id}"),
                workspace_id=c.ws.id,
                account_id=csrc.account_id,
                first_name=csrc.first_name,
                last_name=csrc.last_name,
                email=f"  {(csrc.email or '').upper()} ",
                email_status="unknown",
                title=csrc.title,
                seniority=csrc.seniority,
                department=csrc.department,
                lifecycle_stage="lead",
                source="demo_seed:list_import",
                data_origin="demo",
                created_at=c.d(-30),
            )
        )
        counts["duplicate_contact"] += 1
    for _ in range(5):  # same person, alias email
        csrc = next(cit)
        acct = next(a for a in c.accounts if a.id == csrc.account_id)
        alias = f"{(csrc.first_name or 'x')[0]}{csrc.last_name}@{acct.domain or 'unknown.example'}".lower()
        c.contacts[acct.id].append(
            Contact(
                id=uid("contact", f"alias:{csrc.id}"),
                workspace_id=c.ws.id,
                account_id=csrc.account_id,
                first_name=csrc.first_name,
                last_name=csrc.last_name,
                email=alias,
                email_status="unknown",
                title=csrc.title,
                seniority=csrc.seniority,
                department=csrc.department,
                lifecycle_stage="lead",
                source="demo_seed:event_scan",
                data_origin="demo",
                created_at=c.d(-25),
            )
        )
        counts["duplicate_contact"] += 1
    counts["duplicate_contact"] += 1  # flagship champion duplicate
    malformed = ["{f}.{l}@@{d}", "{f}.{l}.{d}", "{f} {l}@{d}", "{f}.{l}@{d_nodot}", "@{d}"]
    for i in range(25):
        ct = next(cit)
        acct = next(a for a in c.accounts if a.id == ct.account_id)
        d = acct.domain or "unknown.example"
        if i < 15:
            ct.email = malformed[i % len(malformed)].format(
                f=ct.first_name.lower() if ct.first_name else "x",
                l=(ct.last_name or "x").lower(),
                d=d,
                d_nodot=d.split(".")[0],
            )
        else:
            ct.email_status = "invalid"  # well-formed but hard-bounced
        counts["invalid_email"] += 1
    for i in range(3):  # contact lifecycle conflicts
        ct = next(cit)
        ct.lifecycle_stage = "customer"
        counts["lifecycle_conflict"] += 1
        del i
    orphan_domains = [a.domain for a in rng.sample(normal, 10) if a.domain]
    for i in range(14):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        dom = orphan_domains[i] if i < len(orphan_domains) else rng.choice(["gmail.com", "outlook.com"])
        c.db.add(
            Contact(
                id=uid("contact", f"orphan:{i}"),
                workspace_id=c.ws.id,
                account_id=None,
                first_name=first,
                last_name=last,
                email=f"{first}.{last}@{dom}".lower(),
                email_status="unknown",
                title="ML Engineer",
                seniority="ic",
                department="ai_ml",
                lifecycle_stage="lead",
                source="demo_seed:webinar_list",
                data_origin="demo",
                created_at=c.d(-rng.uniform(5, 60)),
            )
        )
        counts["orphan_contact"] += 1
    return dict(counts)


# --------------------------------------------------------------------------------------------------
# Operational history (clearly synthetic, used for trends on the Operations page)
# --------------------------------------------------------------------------------------------------


def _ops_history(c: Ctx) -> None:
    rng = random.Random(RNG_SEED + 7)
    for i in range(30, 0, -1):
        started = c.d(-i) + timedelta(hours=2)
        considered = rng.randint(380, 460)
        changed = rng.randint(20, 90)
        failed = 0 if rng.random() > 0.15 else rng.randint(1, 4)
        status = "succeeded" if failed == 0 else "partial"
        if i in (9, 8):  # a simulated HubSpot incident: two failed nights
            failed, status = changed, "failed"
        c.db.add(
            IntegrationSync(
                workspace_id=c.ws.id,
                provider="hubspot",
                job="reverse_etl_companies",
                direction="outbound",
                object_type="companies",
                status=status,
                is_simulated=True,
                records_considered=considered,
                records_changed=changed,
                records_succeeded=changed - failed,
                records_failed=failed,
                records_skipped=considered - changed,
                retries=failed * 2 if status != "failed" else changed * 2,
                errors=[
                    {
                        "error": "429 Too Many Requests (simulated)"
                        if status != "failed"
                        else "503 Service Unavailable (simulated)",
                        "retryable": True,
                    }
                ]
                if failed
                else [],
                correlation_id=uuid.uuid4().hex[:16],
                started_at=started,
                finished_at=started + timedelta(seconds=rng.uniform(8, 40)),
                duration_ms=int(rng.uniform(8, 40) * 1000),
                trigger="schedule (synthetic history)",
            )
        )
    # Webhook history
    kinds = [("posthog", "product_event"), ("n8n", "signal"), ("posthog", "product_event")]
    for i in range(160):
        src, et = kinds[i % 3]
        received = c.d(-rng.uniform(0.1, 30))
        r = rng.random()
        status = "processed" if r < 0.94 else ("failed" if r < 0.975 else ("dead_letter" if r < 0.985 else "rejected"))
        err = {
            "failed": "OperationalError: database connection reset (simulated)",
            "dead_letter": "ValidationError: event payload missing 'event' (after 3 attempts)",
            "rejected": "signature check failed: signature mismatch",
        }.get(status)
        c.db.add(
            WebhookEvent(
                workspace_id=c.ws.id,
                source=src,
                event_type=et,
                idempotency_key=f"{src}:hist-{i}",
                signature_status="invalid" if status == "rejected" else "valid",
                payload={"synthetic_history": True, "event": "trace_logged" if src == "posthog" else "funding_round"},
                status=status,
                duplicate_count=1 if rng.random() < 0.06 else 0,
                result={},
                error=err,
                attempts=3 if status == "dead_letter" else 1,
                correlation_id=uuid.uuid4().hex[:16],
                received_at=received,
                processed_at=received + timedelta(milliseconds=rng.uniform(20, 400)),
                processing_ms=int(rng.uniform(20, 400)),
                data_origin="demo",
            )
        )


def _workflow_history(c: Ctx) -> None:
    """Synthetic past runs (labeled in trigger_event) so Operations/Workflows show realistic history.

    Current runs are produced by actually executing the engine at the end of seeding.
    """
    rng = random.Random(RNG_SEED + 11)
    wfs = {w.key: w for w in c.db.scalars(select(Workflow).where(Workflow.workspace_id == c.ws.id))}
    funding = [
        (a, s)
        for a in c.accounts
        for s in c.signals[a.id]
        if s["signal_type"] in ("funding_round", "ai_product_launch")
        and -60 <= (s["observed_at"] - c.anchor).days <= -3
    ]
    hiring = [
        (a, s)
        for a in c.accounts
        for s in c.signals[a.id]
        if s["signal_type"] == "ai_hiring_surge" and -45 <= (s["observed_at"] - c.anchor).days <= -2
    ]
    pql = [
        (a, s)
        for a in c.accounts
        for s in c.signals[a.id]
        if s["signal_type"] == "usage_threshold" and -45 <= (s["observed_at"] - c.anchor).days <= -2
    ]
    plan = [("funding-signal-to-outreach", funding), ("ai-hiring-surge-enrichment", hiring), ("pql-to-ae", pql)]
    for wf_key, items in plan:
        wf = wfs[wf_key]
        steps = wf.definition["steps"]
        for a, s in items:
            if a.is_flagship:
                continue  # the flagship's history is produced by really executing the engine (see seed())
            created = s["observed_at"] + timedelta(minutes=rng.uniform(1, 30))
            ctx = {
                "account": {
                    "icp_score": a.icp_score,
                    "score_grade": a.score_grade,
                    "segment": a.segment,
                    "is_customer": a.is_customer,
                }
            }
            passes, cond_results = evaluate_all([Condition.model_validate(x) for x in wf.definition["conditions"]], ctx)
            run = WorkflowRun(
                workspace_id=c.ws.id,
                workflow_id=wf.id,
                workflow_version=1,
                account_id=a.id,
                trigger_event={
                    "type": wf.trigger_type,
                    "event_id": str(s["id"]),
                    "synthetic_history": True,
                    "signal": {"id": str(s["id"]), "signal_type": s["signal_type"], "title": s["title"]},
                },
                idempotency_key=f"wf:{wf_key}:v1:{wf.trigger_type}:{s['id']}",
                correlation_id=uuid.uuid4().hex[:16],
                status="succeeded" if passes else "skipped",
                condition_results=jsonable(cond_results),
                created_at=created,
                started_at=created,
                finished_at=created + timedelta(seconds=rng.uniform(2, 20)),
                data_origin="demo",
                error=None
                if passes
                else "Conditions not met: " + "; ".join(r["condition"] for r in cond_results if not r["passed"]),
            )
            r = rng.random()
            fail_at = None
            step_keys = [x["key"] for x in steps]
            if passes and not a.is_flagship and r < 0.05:
                run.status, fail_at = "dead_letter", step_keys[-1]
            elif passes and not a.is_flagship and r < 0.08:
                run.status, fail_at = "failed", step_keys[0]
            c.db.add(run)
            c.db.flush()
            t = created
            failed_seen = False
            for i, st in enumerate(steps):
                dur = rng.uniform(40, 2500)
                status, attempts, err, logs = "succeeded", 1, None, []
                if not passes or failed_seen:
                    status = "skipped"
                elif st["key"] == fail_at:
                    failed_seen = True
                    status = "failed"
                    dead = run.status == "dead_letter"
                    attempts = st.get("max_attempts", 3) if dead else 1
                    err = (
                        f"retries exhausted: 503 Service Unavailable from {st['action']} (simulated)"
                        if dead
                        else f"ProviderError: upstream timeout in {st['action']} (simulated)"
                    )
                    run.error = f"step '{st['key']}': {err}"
                elif st["key"] == "crm" and (a.is_flagship or rng.random() < 0.12):
                    attempts = 2
                    logs = [
                        {"level": "warn", "msg": "attempt 1: transient error: 429 Too Many Requests (simulated)"},
                        {"level": "info", "msg": "retrying in 2s"},
                        {"level": "info", "msg": "attempt 2: succeeded"},
                    ]
                c.db.add(
                    WorkflowStepRun(
                        run_id=run.id,
                        step_key=st["key"],
                        position=i,
                        action=st["action"],
                        status=status,
                        attempts=attempts if status != "skipped" else 0,
                        max_attempts=st.get("max_attempts", 3),
                        input=st.get("params", {}),
                        output={"synthetic_history": True} if status == "succeeded" else {},
                        error=err,
                        logs=logs,
                        started_at=t if status != "skipped" else None,
                        finished_at=t + timedelta(milliseconds=dur) if status != "skipped" else None,
                        duration_ms=int(dur) if status != "skipped" else None,
                    )
                )
                t += timedelta(milliseconds=dur)


# --------------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------------


def _execute_backdated(
    db: Session,
    ws_id: uuid.UUID,
    account: Account,
    signal: dict[str, Any],
    when: datetime,
    trigger: str = "signal.created",
) -> int:
    """Run a workflow for real, then move its timestamps back to when the signal actually arrived.

    Seeded history is otherwise fabricated: rows that claim a run happened without one ever running. Here the
    engine really executes (real enrichment attempts, real committee inference, real CRM upsert) and only the
    clock is moved, which the run records as `backdated` so the UI can say so.
    """
    from gtmos.models import WorkflowStepRun
    from gtmos.services.workflow_engine import emit_event

    payload: dict[str, Any] = {
        "signal": {
            "id": str(signal["id"]),
            "signal_type": signal["signal_type"],
            "title": signal["title"],
            "observed_at": signal["observed_at"].isoformat(),
        }
    }
    if trigger == "product.pql":
        payload["pql"] = {"event": signal["signal_type"], "signal_id": str(signal["id"])}
    runs = emit_event(db, ws_id, trigger, str(signal["id"]), account, payload, data_origin="demo")
    for run in runs:
        span = (run.finished_at - run.started_at) if run.started_at and run.finished_at else timedelta(seconds=5)
        run.created_at = when
        run.started_at = when
        run.finished_at = when + span
        run.trigger_event = {**(run.trigger_event or {}), "backdated": True}
        offset = when
        for step in db.scalars(
            select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id).order_by(WorkflowStepRun.position)
        ):
            dur = timedelta(milliseconds=step.duration_ms or 0)
            step.started_at = offset
            step.finished_at = offset + dur
            offset += dur
    db.flush()
    return len(runs)


def seed(
    db: Session, size: int = 2000, anchor: datetime | None = None, execute_live_workflows: int = 12
) -> dict[str, Any]:
    from gtmos.services import data_quality
    from gtmos.services.committee_service import recompute_committees_bulk
    from gtmos.services.common import set_actor
    from gtmos.services.crm_sync import run_company_sync
    from gtmos.services.enrichment_service import enrich_account
    from gtmos.services.research_service import generate_research
    from gtmos.services.routing_service import load_rules, load_users, route_account, rule_id_map
    from gtmos.services.scoring_service import rescore_accounts
    from gtmos.services.workflow_engine import emit_event

    anchor = anchor or datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    set_actor("seed")
    ws = Workspace(
        id=uid("workspace", "sentinel-demo"),
        name="Sentinel AI (Demo workspace)",
        slug="sentinel-demo",
        seller_name="Sentinel AI",
        seller_product="Observability, evaluation and reliability infrastructure for enterprise AI agents.",
        mode="demo",
        demo_anchor_at=anchor,
    )
    db.add(ws)
    db.flush()
    c = Ctx(db=db, ws=ws, anchor=anchor, rng=random.Random(RNG_SEED))
    _users(c)
    db.flush()
    _stages_and_types(c)
    _icp_rules_workflows_integrations(c)
    _campaigns(c)
    db.flush()

    universe = company_universe(size)
    for p in universe:
        a = _account_from_profile(c, p)
        c.accounts.append(a)
        c.profiles[a.id] = p
    flagship = c.accounts[0]
    for a in c.accounts[1:]:
        _contacts(c, a, c.profiles[a.id])
    _flagship(c, flagship)
    customers = {a.id for a in c.rng.sample(c.accounts[1:], int(size * 0.035)) if c.profiles[a.id].ai_maturity > 0.4}
    for a in c.accounts[1:]:
        p = c.profiles[a.id]
        _signals_for(c, a, p)
        if a.id in customers:
            _customer(c, a)
            continue
        if c.rng.random() < 0.05 + 0.12 * p.ai_maturity:
            _plg(c, a, p)
        if c.rng.random() < 0.06:
            _webinar(c, a)
        _journey(c, a, p)
    _inbound_opportunities(c, [a for a in c.accounts[1:] if a.id not in customers])
    _provocative_arm_outcomes(c)
    defect_counts = _inject_defects(c)

    db.flush()
    db.add_all(c.accounts)
    db.flush()
    prov_rows: list[dict[str, Any]] = []
    for a in c.accounts:
        _provenance(c, a, prov_rows)
    for i in range(0, len(prov_rows), 2000):
        db.execute(insert(FieldProvenance), prov_rows[i : i + 2000])
    db.add_all(ct for cts in c.contacts.values() for ct in cts)
    db.flush()
    for rows, model in (
        (c.signal_rows, Signal),
        (c.engagement_rows, Engagement),
        (c.transition_rows, StageTransition),
        (c.draft_rows, MessageDraft),  # before activities: sends reference the draft that produced them
        (c.activity_rows, Activity),
        (c.opp_rows, Opportunity),
        (c.assignment_rows, ExperimentAssignment),
        (c.outcome_rows, ExperimentOutcome),
    ):
        for i in range(0, len(rows), 2000):
            if rows[i : i + 2000]:
                db.execute(insert(model), rows[i : i + 2000])
    for a in c.accounts:
        if c.signals[a.id]:
            a.last_signal_at = max(s["observed_at"] for s in c.signals[a.id])
    db.flush()
    log.info(
        "seeded %d accounts, %d contacts, %d signals, %d activities",
        len(c.accounts),
        sum(len(v) for v in c.contacts.values()),
        len(c.signal_rows),
        len(c.activity_rows),
    )

    # Scores, committees, routing (real engines on the synthetic data).
    #
    # Scored at the anchor, not at wall-clock time. Every signal is placed at an offset from the
    # anchor, so scoring at "now" measured decay over an interval that depended on how long the seed
    # had been running — two resets on the same afternoon produced different grade distributions as
    # borderline accounts tipped across a band. Anchoring makes the dataset a pure function of the
    # anchor, which is what "deterministic demo data" has to mean.
    now = c.anchor
    rescore_accounts(db, ws.id, trigger="seed", now=now, write_audit=False)
    live_accounts = list(c.accounts)
    recompute_committees_bulk(db, live_accounts)
    rules, users, rule_ids = load_rules(db, ws.id), load_users(db, ws.id), rule_id_map(db, ws.id)
    chris = c.users["chris"]

    # The earliest real outbound touch per account. The routing decision is placed just before it,
    # because speed to lead is measured against the first time a human actually reached out — not
    # against the stage transition, which a nurtured account can reach long after its first email.
    SLA_TOUCH_TYPES = {"email_sent", "call", "linkedin", "meeting_held"}
    first_activity: dict[uuid.UUID, datetime] = {}
    for row in c.activity_rows:
        if row["type"] not in SLA_TOUCH_TYPES or row.get("account_id") is None:
            continue
        current = first_activity.get(row["account_id"])
        if current is None or row["occurred_at"] < current:
            first_activity[row["account_id"]] = row["occurred_at"]

    # Named accounts: the biggest strategic accounts are assigned to the senior AE by agreement, and no
    # territory rule may move them. Deterministic (largest first) so the demo shows the same set.
    sam = c.users["sam"]
    named = sorted(
        (a for a in live_accounts if a.segment in ("strategic", "enterprise") and not a.is_customer and a.domain),
        key=lambda a: (-(a.employee_count or 0), str(a.id)),
    )[:12]
    for a in named:
        a.is_named_account = True
        a.owner_id = sam.id
    db.flush()

    for a in live_accounts:
        if a.funnel_stage == "prospect" and a.score_grade not in ("A", "B") and not a.is_customer:
            continue
        if not a.is_flagship and a.region == "NA" and a.segment == "enterprise" and c.rng.random() < 0.04:
            a.owner_id = chris.id  # accounts still owned by a departed rep (routing reassigns on next run)
            continue
        first_touch = next(
            (t["changed_at"] for t in c.transition_rows if t["entity_id"] == a.id and t["to_stage"] == "contacted"),
            None,
        )
        sig_times = [s["observed_at"] for s in c.signals[a.id]]
        last_sig = max(sig_times, default=None)
        # Routing happens *before* the first touch, and the gap between them is the speed-to-lead
        # metric. Setting them equal would make every SLA green, which is the one result no real GTM
        # team has ever seen. The lag is mostly small with a long tail: assignments that landed on a
        # Friday, an owner on holiday, a queue nobody watched.
        touch_at = first_activity.get(a.id) or first_touch
        if touch_at is not None:
            lag_hours = c.rng.uniform(0.2, 6) if c.rng.random() < 0.72 else c.rng.uniform(6, 96)
            decided = touch_at - timedelta(hours=lag_hours)
            # A decision cannot precede the signal that triggered it — but "the signal that triggered
            # it" is the last one *before the touch*, not the most recent one overall. Clamping to the
            # latest signal would push the decision past its own first touch on any account that has
            # kept producing signals since.
            trigger_sig = max((x for x in sig_times if x <= touch_at), default=None)
            if trigger_sig is not None and decided < trigger_sig:
                decided = trigger_sig
        else:
            decided = last_sig + timedelta(hours=c.rng.uniform(0.2, 30)) if last_sig else now
        # A signal-driven assignment starts a speed-to-lead clock; a bulk territory assignment does
        # not, and labelling them the same would turn the SLA report into a measure of list size.
        # A qualifying signal on an account nobody then touched is the leak the SLA report exists to
        # find: the clock started and ran out. Rare on purpose — common enough to show, not so common
        # that the metric reads as "this team works nothing".
        dropped = (
            touch_at is None and last_sig is not None and last_sig >= now - timedelta(days=45) and c.rng.random() < 0.3
        )
        if dropped and last_sig is not None:
            decided = last_sig + timedelta(hours=c.rng.uniform(0.5, 8))
        if touch_at:
            trigger = "signal.created" if last_sig else "inbound"
        else:
            trigger = "signal.created" if dropped else "territory_sync"
        d = route_account(
            db,
            a,
            trigger=trigger,
            decided_at=decided,
            users=users,
            rules=rules,
            rule_ids=rule_ids,
            signal_observed_at=last_sig if last_sig and last_sig <= decided else None,
        )
        if d.assigned_user_id:
            for u in users:
                if u.id == str(d.assigned_user_id):
                    object.__setattr__(u, "load", u.load + 1)
    for o in db.scalars(select(Opportunity).where(Opportunity.workspace_id == ws.id)):
        acct = db.get(Account, o.account_id)
        o.owner_id = acct.owner_id if acct else None
    for a in live_accounts:
        for ct in c.contacts.get(a.id, []):
            ct.owner_id = a.owner_id
            if a.funnel_stage in ("qualified", "meeting", "opportunity") and ct.lifecycle_stage == "lead":
                ct.lifecycle_stage = "salesqualifiedlead" if ct.department == "ai_ml" else ct.lifecycle_stage
    db.flush()

    # Enrichment history on a sample (real waterfall against simulated providers)
    # Wide enough that provider disagreement actually appears in the dataset: with 40 accounts the
    # conflict rate produced one or two, which reads as a fluke rather than a property of enrichment.
    sample = [a for a in live_accounts if a.domain and a.score_grade in ("A", "B")][:150]
    for a in sample:
        enrich_account(db, a, trigger="seed:backfill", now=a.last_enriched_at or now)
    rescore_accounts(db, ws.id, [a.id for a in sample], trigger="seed:post-enrichment", now=now, write_audit=False)

    _ops_history(c)
    _workflow_history(c)
    db.flush()

    # Research for the flagship and top accounts (deterministic generator; drafts only)
    top = sorted((a for a in live_accounts if a.domain and not a.is_customer), key=lambda a: -(a.icp_score or 0))[:8]
    for a in [flagship, *[t for t in top if t.id != flagship.id]]:
        generate_research(db, a, actor="seed", use_llm=False)

    # Fill the approval queue with drafts produced by the real personalization engine (never sent).
    from gtmos.services.outreach_service import draft_outreach, pick_recipient

    hot = sorted(
        (
            a
            for a in live_accounts
            if a.score_grade in ("A", "B") and not a.is_customer and not a.is_flagship and a.domain
        ),
        key=lambda a: -(a.intent_score or 0),
    )[:8]
    for a in hot:
        contact = pick_recipient(db, a)
        if contact is not None:
            draft_outreach(db, a, contact, channels=["email", "linkedin"], actor="seed", initial_status="review")

    # Execute the real workflow engine on the most recent signals so the approval queue, routing log and
    # simulated CRM sync contain genuinely produced records.
    recent = sorted(
        (
            (a, s)
            for a in live_accounts
            for s in c.signals[a.id]
            if s["signal_type"] in ("funding_round", "ai_product_launch")
            and not a.is_flagship
            and (s["observed_at"] - anchor).days >= -10
            and (a.icp_score or 0) >= 75
        ),
        key=lambda t: t[1]["observed_at"],
        reverse=True,
    )[:execute_live_workflows]
    executed = 0
    for a, s in recent:
        runs = emit_event(
            db,
            ws.id,
            "signal.created",
            str(s["id"]),
            a,
            {
                "signal": {
                    "id": str(s["id"]),
                    "signal_type": s["signal_type"],
                    "title": s["title"],
                    "observed_at": s["observed_at"].isoformat(),
                }
            },
            data_origin="demo",
        )
        executed += len(runs)

    # The flagship's own history: really executed, then backdated to the signals that triggered it. The
    # funding → outreach workflow is deliberately left un-run so the demo can trigger it live.
    for sig_type, minutes in (("ai_hiring_surge", 14), ("usage_threshold", 9)):
        sig = next((x for x in c.signals[flagship.id] if x["signal_type"] == sig_type), None)
        if sig is not None:
            executed += _execute_backdated(db, ws.id, flagship, sig, sig["observed_at"] + timedelta(minutes=minutes))

    sync = run_company_sync(db, ws.id, job="reverse_etl_companies", trigger="seed")
    # The session runs with autoflush off, so pending work (notably the enrichment backfill's provider
    # conflicts) must reach the database before the scan queries for it, or the summary under-reports.
    db.flush()
    dq = data_quality.scan(db, ws.id, write_audit=False)
    db.add(
        AuditEvent(
            workspace_id=ws.id,
            actor_type="system",
            actor="seed",
            action="workspace.seeded",
            entity_type="workspace",
            entity_id=ws.id,
            after={"accounts": len(c.accounts)},
            reason="Deterministic DEMO dataset",
            occurred_at=now,
            correlation_id="seed",
        )
    )
    db.flush()
    return {
        "workspace_id": str(ws.id),
        "anchor": anchor.isoformat(),
        "accounts": len(c.accounts) + defect_counts.get("duplicate_account", 0),
        "contacts": sum(len(v) for v in c.contacts.values()) + defect_counts.get("orphan_contact", 0),
        "signals": len(c.signal_rows),
        "activities": len(c.activity_rows),
        "engagements": len(c.engagement_rows),
        "opportunities": len(c.opp_rows),
        "experiment_assignments": len(c.assignment_rows),
        "workflow_runs_executed": executed,
        "reverse_etl": {"status": sync.status, "changed": sync.records_changed},
        "injected_defects": defect_counts,
        "data_quality_open": dq["open_by_rule"],
        "flagship_account_id": str(flagship.id),
    }


def dates_for_demo(anchor: date) -> dict[str, str]:  # pragma: no cover - documentation helper
    return {"anchor": anchor.isoformat()}
