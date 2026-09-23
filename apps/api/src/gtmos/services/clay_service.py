"""Clay → GTMOS ingestion.

Clay does not define an outbound payload: the HTTP API column's body is a JSON template the operator
hand-writes (`docs/research/clay.md` §4a), so *GTMOS* owns this contract and `docs/clay-live-setup.md`
is the thing a Clay table is configured against. Two consequences shape everything below.

1. **Clay supplies no provenance envelope.** There is no uniform Clay confidence and no documented
   per-cell enrichment timestamp (§9). Provenance is therefore *constructed* at this boundary: the
   source is always `clay`, narrowed to `clay:<provider>` only when the table was configured to emit
   the winning waterfall provider, confidence is carried only when a column supplies one, and
   `observed_at` falls back to our own receipt time rather than being invented.
2. **Partial rows are the normal case.** A completed Clay run can contain failed items, and cells
   carry `success | empty | pending | errored` (§10). A row where three of eight columns resolved is
   a successful delivery with five skipped fields, not a failure.

The merge itself is not re-implemented here. It calls `domain.enrichment.decide()` and the conflict
policy that provider enrichment uses, so a Clay value obeys exactly the same rules: it never
overwrites a manual lock, and a material disagreement with an existing confident value raises a
`conflict` instead of silently winning.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gtmos.config import get_settings
from gtmos.domain.enrichment import (
    DEFAULT_MIN_CONFIDENCE,
    Attempt,
    Disagreement,
    ExistingValue,
    FieldDecision,
    apply_conflict,
    decide,
    detect_conflict,
)
from gtmos.domain.matching import normalize_domain, normalize_email
from gtmos.integrations.clay import verify_clay
from gtmos.models import Account, Contact, FieldProvenance, Workspace
from gtmos.seed.profiles import segment_for
from gtmos.services import webhook_service
from gtmos.services.common import audit, jsonable, utcnow
from gtmos.services.enrichment_service import provenance_for

SOURCE = "clay"
EVENT_TYPE = "enriched_record"

# Clay publishes no uniform confidence score (`docs/research/clay.md` §9), so a Clay value that carries
# none is scored by GTMOS policy, not by Clay: above the 0.6 bar, because a waterfall only emits a value
# when a provider hit, and below a named-provider or human-verified value, because we cannot see which
# vendor answered or how sure it was. This number is ours and is deliberately not called a Clay score.
CLAY_DEFAULT_CONFIDENCE = 0.7


class ClaySignatureError(Exception):
    """The delivery did not carry a valid X-Clay-Signature. Nothing is stored and nothing is processed."""


@dataclass(frozen=True)
class FieldSpec:
    kind: str  # text | int | float | fraction | list | domain | email | choice
    aliases: tuple[str, ...] = ()
    max_length: int | None = None
    choices: frozenset[str] | None = None


# Clay column names are whatever the operator typed, so every GTMOS field accepts a few spellings.
# Keys here are already normalised (`Company Domain` → `company_domain`).
ACCOUNT_FIELDS: dict[str, FieldSpec] = {
    "name": FieldSpec("text", ("company_name", "company", "account_name"), max_length=300),
    "domain": FieldSpec("domain", ("company_domain", "website", "company_website", "url")),
    "description": FieldSpec("text", ("company_description", "summary", "about")),
    "industry": FieldSpec("text", ("company_industry", "sector"), max_length=120),
    "sub_industry": FieldSpec("text", ("subindustry", "sub_sector", "niche"), max_length=120),
    "employee_count": FieldSpec("int", ("employees", "headcount", "employee_size", "company_size")),
    "employee_growth_12m": FieldSpec("fraction", ("headcount_growth", "employee_growth", "growth_12m")),
    "annual_revenue_usd": FieldSpec("int", ("annual_revenue", "revenue", "estimated_revenue")),
    "founded_year": FieldSpec("int", ("founded", "year_founded")),
    "country": FieldSpec("choice", ("company_country", "country_code"), max_length=2),
    "region": FieldSpec("choice", ("company_region",), choices=frozenset({"NA", "EMEA", "APAC", "LATAM"})),
    "city": FieldSpec("text", ("company_city", "hq_city", "location_city"), max_length=120),
    "funding_stage": FieldSpec("text", ("latest_funding_stage", "stage"), max_length=40),
    "total_funding_usd": FieldSpec("int", ("total_funding", "total_raised", "funding_total")),
    "technologies": FieldSpec("list", ("tech_stack", "technology", "tools")),
    "ai_team_size": FieldSpec("int", ("ai_headcount", "ml_team_size")),
    "ai_open_roles": FieldSpec("int", ("ai_job_openings", "ai_roles_open", "open_ai_roles")),
    "linkedin_url": FieldSpec("text", ("company_linkedin", "linkedin", "linkedin_company_url"), max_length=500),
}

CONTACT_FIELDS: dict[str, FieldSpec] = {
    "first_name": FieldSpec("text", ("firstname", "given_name"), max_length=120),
    "last_name": FieldSpec("text", ("lastname", "family_name", "surname"), max_length=120),
    "email": FieldSpec("email", ("work_email", "business_email", "email_address"), max_length=320),
    "email_status": FieldSpec(
        "choice",
        ("email_verification", "email_validity", "email_verification_status"),
        choices=frozenset({"valid", "invalid", "risky", "unknown"}),
    ),
    "title": FieldSpec("text", ("job_title", "position"), max_length=200),
    "seniority": FieldSpec(
        "choice", ("seniority_level",), choices=frozenset({"c_suite", "vp", "director", "manager", "ic"})
    ),
    "department": FieldSpec("text", ("function", "team"), max_length=60),
    "linkedin_url": FieldSpec("text", ("linkedin", "person_linkedin", "linkedin_profile"), max_length=500),
    "country": FieldSpec("choice", ("person_country",), max_length=2),
}

# A cell that did not resolve. Clay distinguishes these and so must we: `empty` cost nothing and means
# no provider had the answer, `errored` means a provider broke, `pending` means the run is not done.
UNRESOLVED_CELL_STATUSES = frozenset({"empty", "pending", "errored", "error", "failed", "skipped"})

CONTACT_HINTS = frozenset({"contact", "person", "people", "lead", "prospect"})


def _normalize_key(key: str) -> str:
    out = "".join(c if c.isalnum() else "_" for c in key.strip().casefold())
    return "_".join(part for part in out.split("_") if part)


def _index(spec_map: dict[str, FieldSpec]) -> dict[str, str]:
    index: dict[str, str] = {}
    for name, spec in spec_map.items():
        index[name] = name
        for alias in spec.aliases:
            index[alias] = name
    return index


ACCOUNT_INDEX = _index(ACCOUNT_FIELDS)
CONTACT_INDEX = _index(CONTACT_FIELDS)


@dataclass
class ClayCell:
    """One Clay column's answer for one row, with whatever provenance the table was told to emit."""

    field: str
    value: Any
    provider: str | None = None
    confidence: float | None = None
    observed_at: datetime | None = None
    others: list[Disagreement] = dataclasses.field(default_factory=list)

    @property
    def source(self) -> str:
        # Always `clay`, narrowed only when the waterfall was configured to name its winner. A field
        # stamped plain `clay` is honest about not knowing which vendor behind Clay produced it.
        return f"clay:{self.provider}"[:60] if self.provider else SOURCE


@dataclass
class ClayRow:
    row_id: str | None
    run_id: str | None
    table_id: str | None
    observed_at: datetime | None
    account: list[ClayCell]
    contact: list[ClayCell]
    skipped: list[dict[str, str]]
    unmapped: list[str]
    routine_run_id: str | None = None

    @property
    def is_notification(self) -> bool:
        """Clay's own signed webhook is a *notification*, not data: `{webhookId, createdAt, data}`."""
        return self.routine_run_id is not None and not self.account and not self.contact


def _parse_timestamp(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _coerce(spec: FieldSpec, raw: Any) -> tuple[Any, str | None]:
    """Return (value, rejection reason). A value we cannot coerce is skipped, never guessed at."""
    if raw is None:
        return None, "empty"
    if spec.kind == "list":
        items = raw if isinstance(raw, list) else str(raw).split(",")
        out = [
            str(i.get("name") if isinstance(i, dict) else i).strip()
            for i in items
            if (i.get("name") if isinstance(i, dict) else i) not in (None, "")
        ]
        cleaned = [v for v in out if v]
        return (cleaned, None) if cleaned else (None, "empty")
    if isinstance(raw, str) and not raw.strip():
        return None, "empty"
    if spec.kind in ("int", "float", "fraction"):
        return _coerce_number(spec, raw)
    text = str(raw).strip()
    if spec.kind == "domain":
        domain = normalize_domain(text)
        return (domain, None) if domain else (None, "not a parseable domain")
    if spec.kind == "email":
        email = normalize_email(text)
        return (email, None) if email else (None, "not a parseable email address")
    if spec.kind == "choice":
        candidate = text.replace(" ", "_").replace("-", "_")
        if spec.choices is not None:
            lowered = candidate.casefold()
            match = next((c for c in spec.choices if c.casefold() == lowered), None)
            return (match, None) if match else (None, f"not one of {sorted(spec.choices)}")
        # An unconstrained choice is an ISO-3166 alpha-2 code: a full country name would be silently
        # truncated to two characters by the column, which is worse than not storing it.
        if spec.max_length == 2:
            return (candidate.upper(), None) if len(candidate) == 2 else (None, "expected an ISO-3166 alpha-2 code")
    return (text[: spec.max_length] if spec.max_length else text), None


def _coerce_number(spec: FieldSpec, raw: Any) -> tuple[Any, str | None]:
    if isinstance(raw, bool):
        return None, "expected a number"
    text = str(raw).strip()
    percent = text.endswith("%")
    cleaned = text.removesuffix("%").replace(",", "").replace("$", "").replace("_", "").strip()
    try:
        number = float(cleaned)
    except ValueError:
        return None, "expected a number"
    if spec.kind == "int":
        return round(number), None
    if spec.kind == "fraction":
        # Clay tables express growth either way; "25%" and 0.25 are the same fact.
        return (number / 100.0 if percent or abs(number) > 1.5 else number), None
    return number, None


def _unwrap(raw: Any) -> tuple[Any, dict[str, Any]]:
    """A cell is either a bare value or `{value, provider, confidence, observed_at, status, others}`."""
    if isinstance(raw, dict) and ("value" in raw or "status" in raw):
        return raw.get("value"), raw
    return raw, {}


def _cell(
    field_name: str, spec: FieldSpec, raw: Any, envelope_observed: datetime | None
) -> tuple[ClayCell | None, str]:
    value, meta = _unwrap(raw)
    status = str(meta.get("status") or "").strip().casefold()
    if status and status in UNRESOLVED_CELL_STATUSES:
        return None, status
    coerced, reason = _coerce(spec, value)
    if coerced is None or coerced == [] or coerced == "":
        return None, reason or "empty"
    raw_confidence = meta.get("confidence")
    confidence = (
        float(raw_confidence)
        if isinstance(raw_confidence, int | float) and not isinstance(raw_confidence, bool)
        else None
    )
    others = [
        Disagreement(
            provider=f"clay:{o.get('provider')}"[:60] if o.get("provider") else SOURCE,
            value=_coerce(spec, o.get("value"))[0],
            confidence=float(o["confidence"]) if isinstance(o.get("confidence"), int | float) else None,
        )
        for o in (meta.get("others") or [])
        if isinstance(o, dict) and _coerce(spec, o.get("value"))[0] is not None
    ]
    return (
        ClayCell(
            field=field_name,
            value=coerced,
            provider=str(meta["provider"]).strip() or None if meta.get("provider") else None,
            confidence=confidence,
            observed_at=_parse_timestamp(meta.get("observed_at")) or envelope_observed,
            others=others,
        ),
        "ok",
    )


IDENTITY_KEYS = {
    "clay_row_id": ("row_id", "rowid", "clay_row", "record_id"),
    "clay_run_id": ("run_id", "routine_run_id", "clay_run"),
    "clay_table_id": ("table_id", "clay_table"),
}
# Envelope keys carry the delivery, not the record. They are not "unmapped columns" — reporting them
# as such would bury the one column whose name the operator actually got wrong.
ENVELOPE_KEYS = frozenset(
    {"observed_at", "created_at", "createdat", "webhookid", "webhook_id", "data", "account", "contact"}
    | set(IDENTITY_KEYS)
    | {a for aliases in IDENTITY_KEYS.values() for a in aliases}
)


def parse_row(payload: Any) -> ClayRow:
    """Parse a Clay delivery into typed cells. Never raises on unexpected columns — they are reported."""
    if not isinstance(payload, dict):
        raise ValueError("a Clay webhook body must be a JSON object")
    flat = {_normalize_key(k): v for k, v in payload.items()}

    def identity(canonical: str) -> str | None:
        for key in (canonical, *IDENTITY_KEYS[canonical]):
            value = flat.get(key)
            if isinstance(value, str | int) and str(value).strip():
                return str(value).strip()[:120]
        return None

    envelope_observed = _parse_timestamp(flat.get("observed_at") or flat.get("createdat") or flat.get("created_at"))
    data = flat.get("data") if isinstance(flat.get("data"), dict) else {}
    routine_run_id = None
    if isinstance(data, dict) and isinstance(data.get("routine_run_id"), str):
        routine_run_id = data["routine_run_id"]

    nested_account = flat.get("account") if isinstance(flat.get("account"), dict) else None
    nested_contact = flat.get("contact") if isinstance(flat.get("contact"), dict) else None
    if nested_account is None and nested_contact is None:
        # A flat row is what an HTTP API column produces most naturally, so both shapes are accepted.
        account_raw = {k: v for k, v in flat.items() if k in ACCOUNT_INDEX}
        contact_raw = {
            _strip_contact_prefix(k): v
            for k, v in flat.items()
            if _strip_contact_prefix(k) in CONTACT_INDEX and k not in ACCOUNT_INDEX
        }
        flat_unmapped = [
            k
            for k in flat
            if k not in ACCOUNT_INDEX and _strip_contact_prefix(k) not in CONTACT_INDEX and k not in ENVELOPE_KEYS
        ]
    else:
        account_raw = {_normalize_key(k): v for k, v in (nested_account or {}).items()}
        contact_raw = {_normalize_key(k): v for k, v in (nested_contact or {}).items()}
        flat_unmapped = []

    account_cells, account_skipped, account_unmapped = _cells(
        account_raw, ACCOUNT_INDEX, ACCOUNT_FIELDS, envelope_observed, "account"
    )
    contact_cells, contact_skipped, contact_unmapped = _cells(
        contact_raw, CONTACT_INDEX, CONTACT_FIELDS, envelope_observed, "contact"
    )
    return ClayRow(
        row_id=identity("clay_row_id"),
        run_id=identity("clay_run_id") or routine_run_id,
        table_id=identity("clay_table_id"),
        observed_at=envelope_observed,
        account=account_cells,
        contact=contact_cells,
        skipped=account_skipped + contact_skipped,
        unmapped=sorted(set(account_unmapped) | set(contact_unmapped) | set(flat_unmapped)),
        routine_run_id=routine_run_id,
    )


def _strip_contact_prefix(key: str) -> str:
    for hint in CONTACT_HINTS:
        if key.startswith(f"{hint}_"):
            return key.removeprefix(f"{hint}_")
    return key


def _cells(
    raw: dict[str, Any],
    index: dict[str, str],
    specs: dict[str, FieldSpec],
    envelope_observed: datetime | None,
    entity: str,
) -> tuple[list[ClayCell], list[dict[str, str]], list[str]]:
    cells: list[ClayCell] = []
    skipped: list[dict[str, str]] = []
    unmapped: list[str] = []
    for key, value in raw.items():
        name = index.get(key)
        if name is None:
            unmapped.append(key)
            continue
        cell, reason = _cell(name, specs[name], value, envelope_observed)
        if cell is None:
            # Partial enrichment: one unresolved column must not cost us the seven that resolved.
            skipped.append({"entity": entity, "field": name, "reason": reason})
            continue
        cells.append(cell)
    return cells, skipped, unmapped


def _existing(entity: Any, prov: dict[str, FieldProvenance], name: str) -> ExistingValue | None:
    value = getattr(entity, name, None)
    if value in (None, "", []):
        return None
    p = prov.get(name)
    return ExistingValue(
        value,
        p.confidence if p else 0.5,
        p.source if p else "unknown",
        p.observed_at if p else None,
        p.is_manual_lock if p else False,
    )


def _conflict_payload(decision: FieldDecision, now: datetime) -> dict[str, Any] | None:
    if decision.conflict is None:
        return None
    c = decision.conflict
    return {
        "chosen_value": jsonable(c.chosen_value),
        "chosen_provider": c.chosen_provider,
        "others": [{"provider": o.provider, "value": jsonable(o.value), "confidence": o.confidence} for o in c.others],
        "material": c.material,
        "explanation": c.explanation,
        "observed_at": now.isoformat(),
    }


def _merge(
    db: Session,
    workspace_id: uuid.UUID,
    entity: Any,
    entity_type: str,
    cells: list[ClayCell],
    now: datetime,
) -> dict[str, Any]:
    """Apply Clay's cells through the standard merge policy and persist provenance for each one."""
    prov = provenance_for(db, entity.id)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    outcome: dict[str, list[str]] = {"set": [], "updated": [], "kept": [], "conflicted": []}
    conflicts: list[dict[str, Any]] = []

    for cell in cells:
        existing = _existing(entity, prov, cell.field)
        confidence = cell.confidence if cell.confidence is not None else CLAY_DEFAULT_CONFIDENCE
        candidate = Attempt(
            field=cell.field,
            provider=cell.source,
            position=0,
            outcome="hit",
            value=cell.value,
            confidence=confidence,
        )
        decision = decide(cell.field, existing, candidate, now)
        # Every answer the delivery carries, plus the incumbent, is a second opinion. `detect_conflict`
        # drops whichever one won, so the same list works whether Clay or the existing value prevailed.
        observations = [*cell.others, Disagreement(cell.source, cell.value, confidence)]
        if existing is not None:
            observations.append(Disagreement(existing.source, existing.value, existing.confidence))
        decision = apply_conflict(decision, detect_conflict(decision, observations, DEFAULT_MIN_CONFIDENCE), existing)
        conflict = _conflict_payload(decision, now)
        if conflict is not None:
            conflicts.append({"field": cell.field, **conflict})

        if decision.action in ("set", "update"):
            before[cell.field] = jsonable(getattr(entity, cell.field, None))
            setattr(entity, cell.field, decision.value)
            after[cell.field] = jsonable(decision.value)
            outcome["set" if decision.action == "set" else "updated"].append(cell.field)
            row = prov.get(cell.field)
            if row is None:
                row = FieldProvenance(
                    workspace_id=workspace_id, entity_type=entity_type, entity_id=entity.id, field=cell.field
                )
                db.add(row)
                prov[cell.field] = row
            row.value = jsonable(decision.value)
            row.source = (decision.provider or SOURCE)[:60]
            row.confidence = decision.confidence or 0.0
            row.observed_at = cell.observed_at or now
            row.conflict = conflict
            continue

        outcome["conflicted" if decision.action == "conflict" else "kept"].append(cell.field)
        row = prov.get(cell.field)
        if row is None and decision.action == "conflict" and existing is not None:
            # The field already held a value with no provenance row (seeded or CRM-typed). Losing the
            # conflict here would hide it forever, so the row is created recording what we do know.
            row = FieldProvenance(
                workspace_id=workspace_id,
                entity_type=entity_type,
                entity_id=entity.id,
                field=cell.field,
                value=jsonable(existing.value),
                source=existing.source[:60],
                confidence=existing.confidence,
                observed_at=existing.observed_at or now,
            )
            db.add(row)
            prov[cell.field] = row
        if row is not None:
            if conflict is not None:
                row.conflict = conflict
            if decision.action == "keep_existing" and decision.confidence:
                row.confidence = max(row.confidence, decision.confidence)

    if entity_type == "account" and "employee_count" in after:
        entity.segment = segment_for(entity.employee_count)
    return {"outcome": outcome, "before": before, "after": after, "conflicts": conflicts}


def _find_account(db: Session, workspace_id: uuid.UUID, domain: str) -> Account | None:
    return db.scalars(
        select(Account).where(
            Account.workspace_id == workspace_id, Account.domain == domain, Account.merged_into_id.is_(None)
        )
    ).first()


def apply_row(db: Session, workspace_id: uuid.UUID, row: ClayRow, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    result: dict[str, Any] = {
        "source": SOURCE,
        "clay_row_id": row.row_id,
        "clay_run_id": row.run_id,
        "clay_table_id": row.table_id,
        "skipped_fields": row.skipped,
        "unmapped_columns": row.unmapped,
    }
    if row.is_notification:
        # Clay's own signed webhook only says "a run finished"; the data is pulled afterwards with the
        # Public API. Recording it is the whole job here — fetching needs a key GTMOS may not have.
        client_enabled = bool(get_settings().clay_api_key)
        result |= {
            "kind": "routine_run_notification",
            "routine_run_id": row.routine_run_id,
            "fetched": False,
            "note": (
                "Notification recorded. Results are pulled with GET /routines/run/{id}/results"
                + ("." if client_enabled else "; CLAY_API_KEY is not configured, so nothing was fetched.")
            ),
        }
        return result

    domain_cell = next((c for c in row.account if c.field == "domain"), None)
    email_cell = next((c for c in row.contact if c.field == "email"), None)
    domain = domain_cell.value if domain_cell else None
    if domain is None and email_cell is not None:
        domain = normalize_domain(str(email_cell.value).split("@", 1)[1])
    if domain is None:
        # Without a domain there is no identity to resolve against, and guessing one would create
        # duplicate accounts that are far more expensive than a dropped row.
        result |= {"kind": "enriched_record", "matched": False, "reason": "no company domain in the row"}
        return result

    account = _find_account(db, workspace_id, domain)
    created_account = account is None
    if account is None:
        name_cell = next((c for c in row.account if c.field == "name"), None)
        account = Account(
            workspace_id=workspace_id,
            name=str(name_cell.value) if name_cell else domain,
            domain=domain,
            source=SOURCE,
            data_origin="live",
        )
        db.add(account)
        db.flush()

    account_cells = [c for c in row.account if c.field != "domain"]
    account_merge = _merge(db, workspace_id, account, "account", account_cells, now)
    account.last_enriched_at = now

    contact_result: dict[str, Any] | None = None
    if email_cell is not None:
        email = str(email_cell.value)
        contact = db.scalars(
            select(Contact).where(Contact.workspace_id == workspace_id, func.lower(Contact.email) == email)
        ).first()
        created_contact = contact is None
        if contact is None:
            contact = Contact(
                workspace_id=workspace_id,
                account_id=account.id,
                email=email,
                source=SOURCE,
                data_origin="live",
            )
            db.add(contact)
            db.flush()
        elif contact.account_id is None:
            contact.account_id = account.id
        contact_merge = _merge(
            db, workspace_id, contact, "contact", [c for c in row.contact if c.field != "email"], now
        )
        contact_result = {
            "id": str(contact.id),
            "created": created_contact,
            "fields": contact_merge["outcome"],
            "conflicts": contact_merge["conflicts"],
        }

    if account_merge["after"] or created_account:
        audit(
            db,
            workspace_id,
            "account.enriched",
            "account",
            account.id,
            before=account_merge["before"],
            after=account_merge["after"],
            reason=f"Clay row {row.row_id or '(no id)'}"
            + (f" from run {row.run_id}" if row.run_id else "")
            + f"; {len(row.skipped)} column(s) unresolved",
            actor_type="integration",
            actor=SOURCE,
        )
    db.flush()
    result |= {
        "kind": "enriched_record",
        "matched": True,
        "account": {
            "id": str(account.id),
            "domain": domain,
            "created": created_account,
            "fields": account_merge["outcome"],
            "conflicts": account_merge["conflicts"],
        },
        "contact": contact_result,
    }
    return result


def processor(ws: Workspace) -> webhook_service.Processor:
    def process(db: Session, payload: Any) -> dict[str, Any]:
        return apply_row(db, ws.id, parse_row(payload))

    return process


def idempotency_key(row: ClayRow) -> str | None:
    """Clay's row id is the stable identity of a record; the run id disambiguates re-enrichments.

    `webhook_service.idempotency_key_for` honours an explicit `Idempotency-Key`, which is the supported
    way to give it a key it could not have derived: none of Clay's identifiers are called `id`.
    """
    if row.row_id:
        return f"{SOURCE}:{row.run_id}:{row.row_id}"[:200] if row.run_id else f"{SOURCE}:{row.row_id}"[:200]
    if row.routine_run_id:
        return f"{SOURCE}:run:{row.routine_run_id}"[:200]
    return None


def receive(
    db: Session,
    ws: Workspace,
    headers: dict[str, str],
    body: bytes,
    *,
    method: str = "POST",
    uri: str = "",
) -> webhook_service.ReceiveResult:
    """Verify Clay's signature, then hand the delivery to the shared ingestion pipeline.

    The signature is checked here rather than inside `webhook_service.verify_request` because that
    verifier is keyed by source and knows three schemes, none of them Clay's. Forking the ingestion
    path to add a fourth would cost Clay its dedupe, storage and replay, so instead the verified
    outcome is passed to the pipeline as the internal shared-token attestation: a delivery that failed
    Clay's HMAC never reaches `receive()` at all, and a deployment that has WEBHOOK_SECRET set does not
    have its verified Clay deliveries rejected by a verifier that cannot read X-Clay-Signature.
    """
    settings = get_settings()
    lowered = {k.lower(): v for k, v in headers.items()}
    if settings.clay_webhook_secret is None:
        verification = webhook_service.VerifyResult("not_configured", "CLAY_WEBHOOK_SECRET not set")
    else:
        ok, why = verify_clay(settings.clay_webhook_secret.get_secret_value(), lowered.get("x-clay-signature"), body)
        verification = webhook_service.VerifyResult("valid" if ok else "invalid", why)
    if verification.status == "not_configured" and settings.env == "production":
        verification = webhook_service.VerifyResult("invalid", "CLAY_WEBHOOK_SECRET must be configured in production")
    if verification.status == "invalid":
        raise ClaySignatureError(verification.detail)

    forwarded = dict(headers)
    if settings.webhook_secret is not None:
        forwarded["X-GTMOS-Webhook-Token"] = settings.webhook_secret.get_secret_value()
    if "idempotency-key" not in lowered and "x-idempotency-key" not in lowered:
        try:
            key = idempotency_key(parse_row(_loads(body)))
        except ValueError:
            key = None
        if key:
            forwarded["Idempotency-Key"] = key

    result = webhook_service.receive(
        db, ws.id, SOURCE, EVENT_TYPE, forwarded, body, processor(ws), method=method, uri=uri
    )
    # The pipeline recorded whatever its own verifier made of the headers; Clay's scheme is what
    # actually gated this delivery, so the stored status must say so rather than "not_configured".
    result.event.signature_status = verification.status
    return result


def _loads(body: bytes) -> Any:
    try:
        return json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        raise ValueError("body is not valid JSON") from exc
