import pytest
from pydantic import ValidationError

from gtmos.domain.matching import match_to_account, normalize_company_name, normalize_domain, normalize_email
from gtmos.domain.pipeline import (
    check_funnel_transition,
    check_lifecycle_transition,
    invalid_history_transitions,
    lifecycle_for_funnel,
)
from gtmos.domain.rules import Condition, evaluate, evaluate_all
from gtmos.domain.workflows import WorkflowDefinition, backoff_seconds, idempotency_key, DEFAULT_WORKFLOWS


def test_condition_operators():
    ctx = {"account": {"score": 82, "segment": "enterprise", "tags": ["ai"], "owner": None}}
    assert evaluate(Condition(field="account.score", op="gte", value=80), ctx)[0]
    assert not evaluate(Condition(field="account.score", op="lt", value=80), ctx)[0]
    assert evaluate(Condition(field="account.segment", op="in", value=["enterprise"]), ctx)[0]
    assert evaluate(Condition(field="account.tags", op="contains", value="ai"), ctx)[0]
    assert evaluate(Condition(field="account.owner", op="not_exists"), ctx)[0]
    assert not evaluate(Condition(field="account.missing", op="eq", value=1), ctx)[0]
    assert not evaluate(Condition(field="account.segment", op="gte", value=5), ctx)[0]  # type mismatch → False
    ok, res = evaluate_all([Condition(field="account.score", op="gte", value=90)], ctx)
    assert not ok and res[0]["actual"] == 82
    with pytest.raises(ValidationError):
        Condition(field="x", op="__import__", value=1)


def test_funnel_transitions():
    assert check_funnel_transition("prospect", "meeting").allowed  # skipping ahead is fine
    assert not check_funnel_transition("meeting", "contacted").allowed
    assert check_funnel_transition("engaged", "lost").allowed
    assert not check_funnel_transition("qualified", "won").allowed
    assert check_funnel_transition("opportunity", "won").allowed
    assert not check_funnel_transition("won", "engaged").allowed
    assert check_funnel_transition("lost", "prospect", recycle=True).allowed
    assert not check_funnel_transition("prospect", "prospect").allowed
    bad = invalid_history_transitions([(None, "prospect"), ("prospect", "won")])
    assert len(bad) == 1


def test_lifecycle_forward_only():
    assert check_lifecycle_transition("lead", "opportunity").allowed
    assert not check_lifecycle_transition("customer", "lead").allowed
    assert lifecycle_for_funnel("opportunity", "lead") == "opportunity"
    assert lifecycle_for_funnel("contacted", "salesqualifiedlead") is None
    assert lifecycle_for_funnel("lost", "lead") is None


def test_domain_email_normalization_and_matching():
    assert normalize_domain("https://www.Kestrel-Analytics.example/about?x=1") == "kestrel-analytics.example"
    assert normalize_domain("not a domain") is None
    assert normalize_email("  Priya@Kestrel.Example ") == "priya@kestrel.example"
    assert normalize_email("bad@") is None
    assert normalize_company_name("Kestrel Analytics, Inc.") == "kestrel analytics"
    known = {"kestrel.example"}
    assert match_to_account(known, email="p@kestrel.example").method == "email_domain"
    assert match_to_account(known, email="p@gmail.com").account_key is None
    assert match_to_account(known, email="p@gmail.com", group_domain="kestrel.example").method == "group_key"
    assert match_to_account(known, email="p@eu.kestrel.example").account_key == "kestrel.example"


def test_workflow_definitions_validate():
    for wf in DEFAULT_WORKFLOWS:
        WorkflowDefinition.model_validate(wf["definition"])
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate({"trigger": {"type": "manual"}, "steps": [{"key": "a", "action": "rm_rf"}]})
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate({"trigger": {"type": "manual"},
                                           "steps": [{"key": "a", "action": "route_account"},
                                                     {"key": "a", "action": "sync_crm"}]})
    assert idempotency_key("wf", 2, "signal.created", "s1") == "wf:wf:v2:signal.created:s1"
    assert [backoff_seconds(i) for i in (1, 2, 3)] == [2.0, 8.0, 32.0]
    assert backoff_seconds(10) == 300.0
