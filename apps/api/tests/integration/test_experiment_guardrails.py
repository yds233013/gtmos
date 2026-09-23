"""Guardrails and practical significance, end to end through the experiments API.

The seeded universe here is small (150 accounts), so the demo experiments are deliberately underpowered and
their guardrails are honestly reported as not-yet-cleared rather than clean. The breach case is therefore
asserted on a purpose-built experiment inserted into the test transaction at the sample size the full demo
dataset reaches, so the assertion is about the pipeline rather than about how many accounts happened to be
generated.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from gtmos.domain.experiments import GUARDRAIL_METRICS
from gtmos.models import Experiment, ExperimentAssignment, ExperimentOutcome, ExperimentVariant
from gtmos.services.common import utcnow

NS = uuid.UUID("2f9b6c1e-1f4d-4f52-9a0a-7b3f4f7c1d20")


def test_seeded_experiments_expose_every_guardrail_through_the_api(client):
    rows = client.get("/api/v1/experiments").json()
    assert rows, "the demo dataset should ship with experiments"
    for row in rows:
        assert row["action"] in {"ship", "do_not_ship", "keep_running", "no_change"}
        assert isinstance(row["guardrail_breaches"], list)
        e = client.get(f"/api/v1/experiments/{row['key']}").json()
        assert set(e["guardrail_policy"]) == set(GUARDRAIL_METRICS)
        for v in e["variants"]:
            assert set(v["guardrails"]) == set(GUARDRAIL_METRICS)
            for g in v["guardrails"].values():
                assert g["ci_low"] <= g["rate"] <= g["ci_high"]
        treatment = next(v["key"] for v in e["variants"] if not v["is_control"])
        for metric, check in e["guardrails"][treatment].items():
            assert check["status"] in {"ok", "watch", "breach", "no_data"}
            assert check["ceiling"] == e["guardrail_policy"][metric]["ceiling"]
            assert check["reason"] and check["rationale"]


def test_the_provocative_subject_arm_wins_replies_and_loses_more_than_it_wins(client):
    """The seeded cautionary tale: guardrails move against the arm that wins the vanity metric."""
    e = client.get("/api/v1/experiments/provocative-subject").json()
    assert e["primary_metric"] == "reply"
    arms = {v["key"]: v for v in e["variants"]}
    reply = e["comparisons"]["treatment"]["reply"]
    assert arms["treatment"]["metrics"]["reply"]["rate"] > arms["control"]["metrics"]["reply"]["rate"]
    # The reply lift is bought, not earned: unsubscribes move the wrong way in the same arm. Whether it is
    # a *confirmed* breach depends on sample size, which is why the assertion is about direction and the
    # ceiling, not about the status — at this seed size (150 accounts) nothing is confirmable.
    unsub = e["guardrails"]["treatment"]["unsubscribe"]
    assert unsub["absolute_lift"] > 0 and unsub["treatment"]["rate"] > unsub["ceiling"]
    assert unsub["status"] in {"watch", "breach"}
    assert reply["mde_abs"] is not None and reply["practical_threshold"] == 0.02
    # Underpowered here by construction, and the payload says so rather than implying a clean result.
    assert e["recommendation"]["action"] in {"keep_running", "do_not_ship"}


def test_a_primary_win_with_a_breached_guardrail_is_never_recommended(client, db: Session, ws):
    """A treatment that beats control on replies and doubles unsubscribes must come back 'do not ship'."""
    key = _build(db, ws.id, replies=(68, 93), unsubs=(1, 7), n=293)
    e = client.get(f"/api/v1/experiments/{key}").json()

    assert e["verdict"] == "treatment_better"  # the statistics still say the treatment won
    unsub = e["guardrails"]["treatment"]["unsubscribe"]
    assert unsub["status"] == "breach"
    assert unsub["treatment"]["ci_low"] > unsub["ceiling"]  # the whole interval sits above the limit

    rec = e["recommendation"]
    assert rec["action"] == "do_not_ship"
    assert rec["blocking_guardrails"] == ["unsubscribe"]
    assert "reply" in rec["reasoning"] and "1.00% ceiling" in rec["reasoning"]
    listed = next(r for r in client.get("/api/v1/experiments").json() if r["key"] == key)
    assert listed["guardrail_breaches"] == ["unsubscribe"] and listed["action"] == "do_not_ship"


def test_a_clean_win_at_the_same_sample_size_does_ship(client, db: Session, ws):
    key = _build(db, ws.id, replies=(68, 93), unsubs=(1, 1), n=293, suffix="clean")
    e = client.get(f"/api/v1/experiments/{key}").json()
    assert e["guardrails"]["treatment"]["unsubscribe"]["status"] == "ok"
    assert e["recommendation"]["action"] == "ship"
    assert e["recommendation"]["blocking_guardrails"] == []


def _build(
    db: Session,
    ws_id: uuid.UUID,
    *,
    replies: tuple[int, int],
    unsubs: tuple[int, int],
    n: int,
    suffix: str = "breach",
) -> str:
    """Insert a two-arm experiment with exact per-arm counts. Rolled back with the test transaction."""
    key = f"guardrail-fixture-{suffix}"
    now = utcnow()
    exp = Experiment(
        id=uuid.uuid5(NS, key),
        workspace_id=ws_id,
        key=key,
        name="Guardrail fixture",
        hypothesis="h1",
        null_hypothesis="h0",
        primary_metric="reply",
        unit="account",
        status="stopped",
        salt=key,
        min_sample_per_variant=250,
        started_at=now,
        ended_at=now,
    )
    db.add(exp)
    db.flush()
    for arm, (r, u) in enumerate(zip(replies, unsubs, strict=True)):
        name = ("control", "treatment")[arm]
        v = ExperimentVariant(
            id=uuid.uuid5(NS, f"{key}:{name}"),
            experiment_id=exp.id,
            key=name,
            name=name,
            is_control=arm == 0,
            weight=0.5,
        )
        db.add(v)
        db.flush()
        for i in range(n):
            aid = uuid.uuid5(NS, f"{key}:{name}:{i}")
            db.add(
                ExperimentAssignment(
                    id=aid,
                    experiment_id=exp.id,
                    variant_id=v.id,
                    unit_id=uuid.uuid5(NS, f"{key}:{name}:unit:{i}"),
                    assigned_at=now,
                    bucket=i,
                )
            )
            for metric, count in (("reply", r), ("unsubscribe", u)):
                if i < count:
                    db.add(
                        ExperimentOutcome(
                            id=uuid.uuid5(NS, f"{key}:{name}:{i}:{metric}"),
                            assignment_id=aid,
                            metric=metric,
                            value=1.0,
                            occurred_at=now,
                        )
                    )
    db.flush()
    return key
