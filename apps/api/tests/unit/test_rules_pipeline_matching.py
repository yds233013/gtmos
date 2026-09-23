import pytest
from pydantic import ValidationError

from gtmos.domain.matching import (
    FUZZY_NAME_THRESHOLD,
    Lead,
    domain_brand,
    is_role_address,
    match_lead_to_account,
    match_to_account,
    normalize_company_name,
    normalize_domain,
    normalize_email,
    registrable_domain,
)
from gtmos.domain.matching_fixtures import EVAL_ACCOUNTS
from gtmos.domain.pipeline import (
    check_funnel_transition,
    check_lifecycle_transition,
    invalid_history_transitions,
    lifecycle_for_funnel,
)
from gtmos.domain.rules import Condition, evaluate, evaluate_all
from gtmos.domain.workflows import DEFAULT_WORKFLOWS, WorkflowDefinition, backoff_seconds, idempotency_key


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
        WorkflowDefinition.model_validate(
            {
                "trigger": {"type": "manual"},
                "steps": [{"key": "a", "action": "route_account"}, {"key": "a", "action": "sync_crm"}],
            }
        )
    assert idempotency_key("wf", 2, "signal.created", "s1") == "wf:wf:v2:signal.created:s1"
    assert [backoff_seconds(i) for i in (1, 2, 3)] == [2.0, 8.0, 32.0]
    assert backoff_seconds(10) == 300.0


def test_company_name_normalization_strips_legal_form_in_several_jurisdictions():
    assert normalize_company_name("Vertex Bio GmbH") == "vertex bio"
    assert normalize_company_name("Northwind Logistics Pte Ltd") == "northwind logistics"
    assert normalize_company_name("さくらAI株式会社") == "さくらai"
    assert normalize_company_name("Orion Manufacturing Co.") == "orion manufacturing"
    # "Group" is not a legal form and is never stripped: a group is often a different legal entity.
    assert normalize_company_name("Northwind Logistics Group") == "northwind logistics group"
    assert registrable_domain("mail.kestrel.co.uk") == "kestrel.co.uk"
    assert registrable_domain("eu.kestrel.example") == "kestrel.example"
    assert domain_brand("https://www.kestrel.co.uk/pricing") == "kestrel"
    assert is_role_address("sales@kestrel.example") and not is_role_address("priya@kestrel.example")


# The matcher's accuracy claim used to live here, scored against a 36-case fixture that the fuzzy threshold
# had also been tuned on. That number was in-sample and is gone; the measurement now lives in
# `test_matching_evaluation.py`, against a 219-case set split into a development half and a held-out half,
# and is written up in `docs/matcher-evaluation.md`. What remains below are behaviour tests: the specific
# decisions the waterfall is supposed to make, asserted directly rather than averaged into a metric. They
# share the account universe with the evaluation set so there is one CRM to reason about, not two.


def test_the_matcher_prefers_no_account_to_a_guessed_one() -> None:
    accounts = EVAL_ACCOUNTS
    # 1. A typo'd domain with no other key. Domains are never fuzzy-matched — one character is the whole
    #    difference between two companies — so this is an unmatched lead, not a wrong one.
    typo = match_lead_to_account(Lead(email="p@kestrel-analytcs.example"), accounts)
    assert typo.account_key is None and typo.method == "none"
    # A company name on the same lead recovers it, which is the mitigation: ask for the company field.
    assert (
        match_lead_to_account(
            Lead(email="p@kestrel-analytcs.example", company_name="Kestrel Analytics"), accounts
        ).account_key
        == "kestrel-analytics.example"
    )
    # 2. "Acme Data Analytics" reads equally well as Acme Data or Acme Analytics. The matcher abstains and
    #    hands both candidates to a reviewer; lowering the bar to catch it buys a wrong account, not a match.
    between = match_lead_to_account(Lead(company_name="Acme Data Analytics"), accounts)
    assert between.account_key is None and between.review_required
    assert {"acme-data.example", "acme-analytics.example"} <= {r.account_key for r in between.rejected}


def test_a_brand_label_on_a_foreign_tld_matches_only_until_a_name_contradicts_it() -> None:
    """The matcher's most expensive tier, and the reason it flags every match it makes for review."""
    accounts = EVAL_ACCOUNTS
    brand = match_lead_to_account(Lead(email="p@orion.de"), accounts)
    assert brand.account_key == "orion.example" and brand.method == "brand_domain" and brand.review_required
    # 'orion.de' is Orion Pharma, and the matcher cannot know that from a domain alone — but it can be told.
    contradicted = match_lead_to_account(Lead(email="p@orion.de", company_name="Orion Pharma"), accounts)
    assert contradicted.account_key is None
    assert [r.reason for r in contradicted.rejected] == [
        "shares the brand label 'orion' but the company names disagree"
    ]


def test_matcher_abstains_instead_of_guessing_between_tied_accounts() -> None:
    tied = match_lead_to_account(Lead(email="p@helio.example"), EVAL_ACCOUNTS)
    assert tied.account_key is None and tied.method == "ambiguous" and tied.review_required
    assert {r.account_key for r in tied.rejected} == {"helio.example", "helio-medical"}
    # Two accounts carrying the same name are the same problem on the name key.
    duplicate = match_lead_to_account(Lead(company_name="Helio Robotics"), EVAL_ACCOUNTS)
    assert duplicate.account_key is None and duplicate.method == "ambiguous"
    # Free-mail never resolves to an account by domain, however many accounts exist.
    assert match_lead_to_account(Lead(email="p@gmail.com"), EVAL_ACCOUNTS).account_key is None
    # An exact domain outranks a name that points elsewhere: keys are tried strongest first.
    crossed = match_lead_to_account(Lead(email="p@acme-data.example", company_name="Acme Analytics"), EVAL_ACCOUNTS)
    assert crossed.account_key == "acme-data.example" and crossed.confidence >= 0.9


def test_the_fuzzy_threshold_is_a_parameter_so_tuning_never_patches_a_global() -> None:
    """A swept threshold has to be passed in; a harness that monkeypatches the constant can leak into prod."""
    lead = Lead(company_name="Acme Data Analytics")
    # At a looser bar the same lead is attached to Acme Analytics, which is the wrong company: the cost of
    # the threshold is visible here rather than argued about.
    assert match_lead_to_account(lead, EVAL_ACCOUNTS, fuzzy_threshold=0.80).account_key == "acme-analytics.example"
    assert match_lead_to_account(lead, EVAL_ACCOUNTS, fuzzy_threshold=FUZZY_NAME_THRESHOLD).account_key is None
