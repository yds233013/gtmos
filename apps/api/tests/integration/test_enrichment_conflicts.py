"""Provider disagreement must reach the surface, not die inside the waterfall.

The waterfall picks one answer per field. The answers it rejected are the interesting ones: a value
three providers agree on and a value one provider won by 0.05 confidence look identical on an account
page unless the disagreement is carried through to it.

Detection itself is proven against the real waterfall in `tests/unit/test_enrichment.py`. These tests
are about what happens to a conflict once it exists — persistence, the data-quality rule, the API —
so the `conflict` fixture guarantees one rather than depending on how many accounts this fixture
happened to seed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from gtmos.models import Account, FieldProvenance
from gtmos.services import data_quality
from gtmos.services.common import utcnow


def _conflicted(db, ws) -> list[FieldProvenance]:
    return list(
        db.scalars(
            select(FieldProvenance).where(FieldProvenance.workspace_id == ws.id, FieldProvenance.conflict.is_not(None))
        )
    )


@pytest.fixture
def conflict(db, ws) -> FieldProvenance:
    """A materially conflicted field, guaranteed: a real one if the dataset has it, else a written one."""
    existing = next((p for p in _conflicted(db, ws) if p.conflict["material"]), None)
    if existing is not None:
        return existing

    account = db.scalars(select(Account).where(Account.workspace_id == ws.id, Account.merged_into_id.is_(None))).first()
    assert account is not None
    account.employee_count = 240
    row = db.scalars(
        select(FieldProvenance).where(
            FieldProvenance.entity_id == account.id, FieldProvenance.field == "employee_count"
        )
    ).first()
    if row is None:
        row = FieldProvenance(
            workspace_id=ws.id,
            entity_type="account",
            entity_id=account.id,
            field="employee_count",
            value=240,
            source="demo_firmographics",
            confidence=0.9,
            observed_at=utcnow(),
        )
        db.add(row)
    row.value = 240
    row.source = "demo_firmographics"
    row.conflict = {
        "chosen_value": 240,
        "chosen_provider": "demo_firmographics",
        "others": [{"provider": "demo_webscan", "value": 4000, "confidence": 0.75}],
        "material": True,
        "explanation": "Kept 240 from demo_firmographics; demo_webscan says 4000.",
        "observed_at": utcnow().isoformat(),
    }
    db.flush()
    return row


def test_the_providers_are_capable_of_disagreeing(db, ws):
    """A demo where every provider always agrees teaches nothing about enrichment.

    Asserted against the provider catalog, not this fixture's sample: how many conflicts a dataset
    contains depends on how many accounts it seeds, which is not the property under test.
    """
    from types import SimpleNamespace

    from gtmos.integrations.enrichment_providers import DemoWebScanProvider

    # Reading the two rate constants and asserting they are positive was the previous version of this
    # test. It executed no provider code at all, so it would have stayed green through any refactor
    # that stopped applying them. Run the provider instead, over enough domains for the documented
    # rates to show up, and assert the disagreement actually appears in the values it returns.
    scanner = DemoWebScanProvider(universe_size=1000)
    # Only the three attributes the scanner reads for these two fields. Constructing a full
    # CompanyProfile here would couple the test to a seed dataclass it is not about.
    profile = SimpleNamespace(industry="Retail", employee_count=1000, technologies=("python",))
    domains = [f"probe-{i}.example" for i in range(400)]

    headcounts = [scanner._value(profile, "employee_count", d).value for d in domains]
    industries = [scanner._value(profile, "industry", d).value for d in domains]

    # An entity mismatch is not noise: it is a different question answered, so the value lands far
    # outside the +/-15% band that ordinary estimation noise produces.
    far_off = [h for h in headcounts if h < profile.employee_count * 0.5 or h > profile.employee_count * 2]
    assert far_off, "the scanner never produced an entity mismatch; headcount disagreement is only noise"

    assert set(industries) != {profile.industry}, "vendors never disagree about industry taxonomy"


def test_a_conflict_records_the_losing_value_and_who_said_it(conflict):
    c = conflict.conflict
    assert c["chosen_provider"]
    assert c["others"], "a conflict with no alternative value is not a conflict"
    for other in c["others"]:
        assert other["provider"] != c["chosen_provider"]
        assert other["value"] is not None
    assert c["explanation"]


def test_no_conflict_is_stored_as_sql_null_not_json_null(db, ws, conflict):
    """`IS NOT NULL` is how both the data-quality rule and the UI ask 'is this field contested?'."""
    uncontested = db.scalars(
        select(FieldProvenance).where(FieldProvenance.workspace_id == ws.id, FieldProvenance.conflict.is_(None))
    ).first()
    assert uncontested is not None, "some field somewhere must be uncontested"
    assert uncontested.conflict is None
    assert all(p.conflict is not None for p in _conflicted(db, ws))


def test_a_material_conflict_becomes_a_data_quality_issue(db, ws, conflict):
    result = data_quality.scan(db, ws.id, write_audit=False)
    material = [p for p in _conflicted(db, ws) if p.conflict["material"]]
    assert result["open_by_rule"].get("provider_conflict") == len(material)
    assert "provider_conflict" in data_quality.RULES
    assert data_quality.RULES["provider_conflict"]["why"]


def test_a_non_material_disagreement_is_recorded_but_does_not_raise_an_issue(db, ws, conflict):
    """Flagging casing and rounding differences would train everyone to ignore the flag."""
    scan = data_quality.scan(db, ws.id, write_audit=False)
    conflicts = _conflicted(db, ws)
    quiet = [p for p in conflicts if not p.conflict["material"]]
    assert scan["open_by_rule"].get("provider_conflict", 0) == len(conflicts) - len(quiet)


def test_the_account_api_exposes_the_conflict_so_the_ui_can_show_it(client, db, ws, conflict):
    db.commit()
    account = db.get(Account, conflict.entity_id)
    assert account is not None
    payload = client.get(f"/api/v1/accounts/{account.id}").json()
    served = payload["provenance"][conflict.field]
    assert served["conflict"] is not None
    assert served["conflict"]["others"][0]["provider"] == conflict.conflict["others"][0]["provider"]
    # Fields nobody disagreed about must not carry an empty conflict object.
    uncontested = [f for f, v in payload["provenance"].items() if f != conflict.field and v["conflict"] is None]
    assert uncontested


def test_a_contested_field_keeps_its_stored_value(db, ws, conflict):
    """The merge policy's promise: a contested update is never applied on confidence alone."""
    for p in _conflicted(db, ws):
        if not p.conflict["material"]:
            continue
        account = db.get(Account, p.entity_id)
        stored = getattr(account, p.field, None)
        rejected = [o["value"] for o in p.conflict["others"]]
        assert stored not in rejected, f"{p.field} on {account.name} took a rejected provider's value"
