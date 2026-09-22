"""Provider disagreement must reach the surface, not die inside the waterfall.

The waterfall picks one answer per field. The answers it rejected are the interesting ones: a value
three providers agree on and a value one provider won by 0.05 confidence look identical on an account
page unless the disagreement is carried through to it.
"""

from __future__ import annotations

from sqlalchemy import select

from gtmos.models import Account, FieldProvenance
from gtmos.services import data_quality


def _conflicted(db, ws) -> list[FieldProvenance]:
    return list(
        db.scalars(
            select(FieldProvenance).where(FieldProvenance.workspace_id == ws.id, FieldProvenance.conflict.is_not(None))
        )
    )


def test_the_dataset_actually_contains_disagreement(db, ws):
    """A demo where every provider always agrees teaches nothing about enrichment.

    The test fixture seeds a fraction of the demo universe, so this asserts the property rather than
    a count; the full dataset carries an order of magnitude more.
    """
    conflicts = _conflicted(db, ws)
    assert conflicts, "no provider disagreement anywhere in the dataset"
    assert any(p.conflict["material"] for p in conflicts)


def test_a_conflict_records_the_losing_value_and_who_said_it(db, ws):
    p = next(x for x in _conflicted(db, ws) if x.conflict["material"])
    c = p.conflict
    assert c["chosen_provider"]
    assert c["others"], "a conflict with no alternative value is not a conflict"
    for other in c["others"]:
        assert other["provider"] != c["chosen_provider"]
        assert other["value"] is not None
    assert c["explanation"]


def test_no_conflict_is_stored_as_sql_null_not_json_null(db, ws):
    """`IS NOT NULL` is how both the data-quality rule and the UI ask 'is this field contested?'."""
    total = db.scalar(select(FieldProvenance).where(FieldProvenance.workspace_id == ws.id).exists().select())
    assert total is True
    assert all(p.conflict is not None for p in _conflicted(db, ws))


def test_a_material_conflict_becomes_a_data_quality_issue(db, ws):
    result = data_quality.scan(db, ws.id, write_audit=False)
    material = [p for p in _conflicted(db, ws) if p.conflict["material"]]
    assert result["open_by_rule"].get("provider_conflict") == len(material)
    assert "provider_conflict" in data_quality.RULES
    assert data_quality.RULES["provider_conflict"]["why"]


def test_a_non_material_disagreement_is_recorded_but_does_not_raise_an_issue(db, ws):
    """Flagging casing and rounding differences would train everyone to ignore the flag."""
    scan = data_quality.scan(db, ws.id, write_audit=False)
    conflicts = _conflicted(db, ws)
    quiet = [p for p in conflicts if not p.conflict["material"]]
    assert scan["open_by_rule"].get("provider_conflict", 0) == len(conflicts) - len(quiet)


def test_the_account_api_exposes_the_conflict_so_the_ui_can_show_it(client, db, ws):
    p = next(x for x in _conflicted(db, ws) if x.conflict["material"])
    account = db.get(Account, p.entity_id)
    assert account is not None
    payload = client.get(f"/api/v1/accounts/{account.id}").json()
    served = payload["provenance"][p.field]
    assert served["conflict"] is not None
    assert served["conflict"]["others"][0]["provider"] == p.conflict["others"][0]["provider"]
    # Fields nobody disagreed about must not carry an empty conflict object.
    uncontested = [f for f, v in payload["provenance"].items() if f != p.field and v["conflict"] is None]
    assert uncontested


def test_a_contested_field_keeps_its_stored_value(db, ws):
    """The merge policy's promise: a contested update is never applied on confidence alone."""
    for p in _conflicted(db, ws):
        if not p.conflict["material"]:
            continue
        account = db.get(Account, p.entity_id)
        stored = getattr(account, p.field, None)
        rejected = [o["value"] for o in p.conflict["others"]]
        assert stored not in rejected, f"{p.field} on {account.name} took a rejected provider's value"
