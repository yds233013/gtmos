import pytest
from pydantic import ValidationError

from gtmos.domain.matching import (
    AccountRef,
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


# A labelled fixture of lead-to-account cases, hard ones first. `None` means "no account is the right
# answer" — a matcher that guesses on these is worse than one that abstains, because a wrongly matched lead
# is routed to the wrong rep and nothing ever raises. The accounts below deliberately include two pairs
# that must never be confused (Acme Data / Acme Analytics, Kestrel Analytics / Kestrel Labs), two accounts
# sharing one corporate domain, and two sharing a brand label on different TLDs.
FIXTURE_ACCOUNTS = (
    AccountRef("kestrel-analytics.example", "Kestrel Analytics", "kestrel-analytics.example", ("Kestrel Data Labs",)),
    AccountRef("kestrel-labs.example", "Kestrel Labs", "kestrel-labs.example"),
    AccountRef("northwind-logistics.example", "Northwind Logistics", "northwind-logistics.example"),
    AccountRef("meridian.co.uk", "Meridian Freight", "https://www.meridian.co.uk"),
    AccountRef("helio.example", "Helio Robotics", "helio.example", ("Sunburst Systems",)),
    AccountRef("helio-robotics.example", "Helio Robotics", "helio-robotics.example"),
    AccountRef("helio-medical", "Helio Medical", "helio.example"),
    AccountRef("acme-data.example", "Acme Data", "acme-data.example"),
    AccountRef("acme-analytics.example", "Acme Analytics", "acme-analytics.example"),
    AccountRef("sakura-ai.example", "さくらAI株式会社", "sakura-ai.example", ("Sakura AI",)),
    AccountRef("vertex-bio.example", "Vertex Bio GmbH", "vertex-bio.example"),
    AccountRef("orion.example", "Orion Manufacturing", "orion.example"),
    AccountRef("bluepeak.example", "Blue Peak Software", "bluepeak.example"),
    AccountRef("cobalt-no-domain", "Cobalt Systems", None),
    AccountRef("summit.example", "Summit Health", "summit.example"),
    AccountRef("summit.io", "Summit Robotics", "summit.io"),
)

LABELLED_LEADS: tuple[tuple[str, Lead, str | None], ...] = (
    ("work email on the account domain", Lead(email="priya@kestrel-analytics.example"), "kestrel-analytics.example"),
    ("email at a regional subdomain", Lead(email="p@eu.kestrel-analytics.example"), "kestrel-analytics.example"),
    (
        "website with scheme, www and path",
        Lead(website="https://www.Northwind-Logistics.example/careers"),
        "northwind-logistics.example",
    ),
    ("country TLD behind a mail subdomain", Lead(email="p@mail.meridian.co.uk"), "meridian.co.uk"),
    ("country site of the same brand", Lead(email="p@meridian.de", company_name="Meridian Freight"), "meridian.co.uk"),
    (
        "free-mail address plus a company name",
        Lead(email="j@gmail.com", company_name="Kestrel Analytics"),
        "kestrel-analytics.example",
    ),
    ("free-mail address and nothing else", Lead(email="j@gmail.com"), None),
    (
        "legal suffix on the lead's company",
        Lead(email="j@gmail.com", company_name="Kestrel Analytics, Inc."),
        "kestrel-analytics.example",
    ),
    (
        "German subsidiary on the .de domain",
        Lead(email="k@vertex-bio.de", company_name="Vertex Bio GmbH"),
        "vertex-bio.example",
    ),
    ("Japanese legal suffix, no domain", Lead(company_name="さくらAI株式会社"), "sakura-ai.example"),
    ("Japanese company on its .jp domain", Lead(email="t@sakura-ai.jp", company_name="さくらAI"), "sakura-ai.example"),
    ("acquired brand used as the company", Lead(company_name="Sunburst Systems"), "helio.example"),
    ("the account's former name", Lead(company_name="Kestrel Data Labs"), "kestrel-analytics.example"),
    ("near-duplicate accounts, right domain", Lead(email="p@acme-data.example"), "acme-data.example"),
    ("near-duplicate accounts, name only", Lead(company_name="Acme Data Inc"), "acme-data.example"),
    ("longer variant of a near-duplicate", Lead(company_name="Acme Data Analytics"), "acme-data.example"),
    ("typo domain with no other key", Lead(email="p@kestrel-analytcs.example"), "kestrel-analytics.example"),
    (
        "typo domain rescued by the name",
        Lead(email="p@kestrel-analytcs.example", company_name="Kestrel Analytics"),
        "kestrel-analytics.example",
    ),
    ("singular/plural name drift", Lead(company_name="Northwind Logistic"), "northwind-logistics.example"),
    (
        "holding-company suffix on the name",
        Lead(company_name="Northwind Logistics Group"),
        "northwind-logistics.example",
    ),
    ("different company, shared first token", Lead(email="p@kestrel-labs.example"), "kestrel-labs.example"),
    ("unrelated company, shared first token", Lead(company_name="Orion Medical"), None),
    ("bare parent brand, several children", Lead(company_name="Acme"), None),
    ("duplicate accounts with one name", Lead(company_name="Helio Robotics"), None),
    ("role address on a known domain", Lead(email="sales@bluepeak.example"), "bluepeak.example"),
    (
        "malformed email, company name given",
        Lead(email="not-an-email", company_name="Blue Peak Software"),
        "bluepeak.example",
    ),
    ("typo in the company name", Lead(email="j@gmail.com", company_name="Blue Peak Softwre"), "bluepeak.example"),
    (
        "product group key beats free-mail",
        Lead(email="j@gmail.com", group_domain="kestrel-analytics.example"),
        "kestrel-analytics.example",
    ),
    ("company that is not in the CRM", Lead(email="p@zenith-unknown.example", company_name="Zenith Unknown"), None),
    (
        "subsidiary with its own name and domain",
        Lead(email="p@northwind-freight.example", company_name="Northwind Freight Solutions"),
        None,
    ),
    ("shop subdomain of a known account", Lead(email="p@shop.orion.example"), "orion.example"),
    (
        "account with no domain in the CRM",
        Lead(email="p@cobaltsystems.example", company_name="Cobalt Systems"),
        "cobalt-no-domain",
    ),
    ("two accounts share a brand label", Lead(email="p@summit.co"), None),
    ("two accounts on one corporate domain", Lead(email="p@helio.example"), None),
    ("same brand label, different company", Lead(email="p@orion.de"), None),
    ("same brand label, name disagrees", Lead(email="p@orion.de", company_name="Orion Pharma"), None),
)


def score_matcher(cases=LABELLED_LEADS, accounts=FIXTURE_ACCOUNTS):
    """Confusion matrix over the fixture. A match to the wrong account counts as both an FP and an FN."""
    tp = fp = fn = tn = 0
    misses = []
    for label, lead, truth in cases:
        got = match_lead_to_account(lead, accounts)
        if truth is not None and got.account_key == truth:
            tp += 1
        elif truth is None and got.account_key is None:
            tn += 1
        else:
            fp += got.account_key is not None
            fn += truth is not None
            misses.append((label, truth, got.account_key, got.method))
    return {
        "n": len(cases),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else 1.0,
        "recall": tp / (tp + fn) if tp + fn else 1.0,
        "misses": misses,
    }


def test_lead_to_account_matching_clears_a_precision_and_recall_floor_on_hard_cases():
    s = score_matcher()
    # Measured when written: 36 cases, 24 TP, 1 FP, 2 FN, 9 TN — precision 0.96, recall 0.92. The floors
    # sit just under that, and precision's floor is the higher of the two on purpose: on a lead-to-account
    # matcher a false positive is silent and a false negative is visible in an unmatched queue.
    assert s["precision"] >= 0.95, s
    assert s["recall"] >= 0.90, s
    assert s["tn"] >= 8, s  # the negatives have to be doing work, or precision means nothing
    assert len(s["misses"]) <= 3, s


def test_the_matcher_misses_these_three_and_the_reason_is_known():
    """The failure modes behind the 0.96/0.92 above, asserted so they stay documented rather than drifting."""
    accounts = FIXTURE_ACCOUNTS
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
    # 2. "Acme Data Analytics" is 64% similar to Acme Data and 85% to Acme Analytics: the nearest neighbour
    #    is the wrong account. Lowering the threshold to catch this case buys a false positive, not a match.
    longer = match_lead_to_account(Lead(company_name="Acme Data Analytics"), accounts)
    assert longer.account_key is None
    assert any(r.account_key == "acme-analytics.example" for r in longer.rejected)
    # 3. The one false positive: a shared brand label on a different TLD, with no company name to contradict
    #    it. 'orion.de' is a different company; the matcher cannot know that from a domain alone, so it
    #    matches at 0.78 and flags the lead for review. Adding a company name blocks it.
    brand = match_lead_to_account(Lead(email="p@orion.de"), accounts)
    assert brand.account_key == "orion.example" and brand.method == "brand_domain" and brand.review_required
    assert match_lead_to_account(Lead(email="p@orion.de", company_name="Orion Pharma"), accounts).account_key is None


def test_matcher_abstains_instead_of_guessing_between_tied_accounts():
    tied = match_lead_to_account(Lead(email="p@helio.example"), FIXTURE_ACCOUNTS)
    assert tied.account_key is None and tied.method == "ambiguous" and tied.review_required
    assert {r.account_key for r in tied.rejected} == {"helio.example", "helio-medical"}
    # Free-mail never resolves to an account by domain, however many accounts exist.
    assert match_lead_to_account(Lead(email="p@gmail.com"), FIXTURE_ACCOUNTS).account_key is None
    # An exact domain outranks a name that points elsewhere: keys are tried strongest first.
    crossed = match_lead_to_account(Lead(email="p@acme-data.example", company_name="Acme Analytics"), FIXTURE_ACCOUNTS)
    assert crossed.account_key == "acme-data.example" and crossed.confidence >= 0.9
