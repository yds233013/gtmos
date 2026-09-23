"""The lead-to-account matcher's accuracy claim, and the guards that keep it from becoming circular again.

The previous version of this claim tuned the fuzzy threshold on the same 36 cases it then reported
precision and recall from. These tests re-derive the threshold from the development split alone and assert
the held-out numbers that `docs/matcher-evaluation.md` publishes, so the document and the code cannot drift
apart without a test going red.

The hard-coded counts below are deliberate. They are the published result; if someone adds a case or moves
the threshold, the numbers in the doc are stale and a failing test is how they find out.
"""

from __future__ import annotations

from gtmos.domain.matching import (
    FUZZY_NAME_THRESHOLD,
    normalize_company_name,
)
from gtmos.domain.matching_fixtures import (
    DEV_CASES,
    EVAL_ACCOUNTS,
    EVAL_CASES,
    TEST_CASES,
    TUNING_BETA,
    bootstrap_interval,
    choose_threshold,
    f_beta,
    score_cases,
    split_for,
    tuning_curve,
)

ACCOUNT_KEYS = {a.key for a in EVAL_ACCOUNTS}


def test_the_labelled_set_is_large_enough_to_be_worth_splitting_and_is_split_in_half() -> None:
    assert len(EVAL_CASES) == 219
    assert len(DEV_CASES) == 103
    assert len(TEST_CASES) == 116
    assert len(DEV_CASES) + len(TEST_CASES) == len(EVAL_CASES)
    # Both halves need enough of each label for precision and recall to mean anything on either one.
    for half in (DEV_CASES, TEST_CASES):
        assert sum(1 for c in half if c.expected is not None) >= 50
        assert sum(1 for c in half if c.expected is None) >= 20


def test_the_split_is_a_hash_of_the_case_id_so_it_cannot_be_re_rolled() -> None:
    """A shuffle can be re-run until the numbers look better. A hash of the id cannot."""
    assert split_for("exact_domain/kestrel-analytics.example") == split_for("exact_domain/kestrel-analytics.example")
    dev_ids = {c.case_id for c in DEV_CASES}
    test_ids = {c.case_id for c in TEST_CASES}
    assert not dev_ids & test_ids
    assert dev_ids | test_ids == {c.case_id for c in EVAL_CASES}
    # Recomputing the assignment from the id alone reproduces the published halves exactly.
    assert {c.case_id for c in EVAL_CASES if split_for(c.case_id) == "test"} == test_ids


def test_every_case_has_a_unique_id_a_real_expected_account_and_a_written_justification() -> None:
    ids = [c.case_id for c in EVAL_CASES]
    assert len(set(ids)) == len(ids)
    for case in EVAL_CASES:
        assert case.expected is None or case.expected in ACCOUNT_KEYS, case.case_id
        # A label nobody can defend in a sentence is a label that should not be in a dataset.
        assert len(case.why) > 30, case.case_id
        assert case.lead.email or case.lead.company_name or case.lead.website or case.lead.group_domain


def test_negative_cases_are_negative_by_construction_not_by_the_matchers_opinion() -> None:
    """The "no account" labels are checkable without running the matcher, which is the point.

    For the two families that carry the most weight in precision — companies absent from the CRM, and
    companies that merely share a word with one — no account's name or alias equals the lead's name once
    normalized. The label therefore does not depend on anything the matcher does.
    """
    known_names = {
        normalize_company_name(n) for a in EVAL_ACCOUNTS for n in (a.name, *a.aliases) if normalize_company_name(n)
    }
    for case in EVAL_CASES:
        if case.family in ("unknown_company", "near_miss_name"):
            assert case.expected is None
            assert normalize_company_name(case.lead.company_name) not in known_names, case.case_id


def test_the_threshold_is_derived_from_the_development_split_alone() -> None:
    rows = tuning_curve(DEV_CASES)
    assert choose_threshold(rows) == FUZZY_NAME_THRESHOLD == 0.87
    by_threshold = {r.threshold: r for r in rows}
    # Precision is monotone-ish upward and recall monotone downward across the sweep, which is what makes
    # the curve readable as a trade-off rather than as noise.
    assert by_threshold[0.70].recall > by_threshold[0.98].recall
    assert by_threshold[0.70].precision < by_threshold[0.98].precision
    # Dev localises the threshold to a plateau, not to a point: 0.85, 0.86 and 0.87 make identical
    # decisions on these 103 cases. The tie is broken upward, toward the value that guesses least.
    plateau = [by_threshold[t] for t in (0.85, 0.86, 0.87)]
    assert {(r.tp, r.fp, r.fn) for r in plateau} == {(74, 0, 4)}
    assert by_threshold[0.88].tp < 74  # and the plateau really does end


def test_the_tuning_rule_weights_precision_above_recall() -> None:
    """F0.5, fixed before the curve was drawn, because the two errors have different blast radii."""
    assert TUNING_BETA == 0.5
    precise = f_beta(precision=0.98, recall=0.90, beta=TUNING_BETA)
    recallful = f_beta(precision=0.90, recall=0.98, beta=TUNING_BETA)
    assert precise > recallful
    assert f_beta(1.0, 0.0, TUNING_BETA) == 0.0  # a matcher that matches nothing is not perfect


def test_held_out_precision_and_recall_are_the_numbers_the_evaluation_doc_publishes() -> None:
    s = score_cases(TEST_CASES, FUZZY_NAME_THRESHOLD)
    assert (s.n, s.tp, s.fp, s.fn, s.tn) == (116, 76, 3, 5, 32)
    assert round(s.precision, 3) == 0.962  # 76/79 predictions
    assert round(s.recall, 3) == 0.938  # 76/81 true matches
    assert round(s.f1, 3) == 0.950
    assert [round(x, 3) for x in s.precision_ci] == [0.894, 0.987]
    assert [round(x, 3) for x in s.recall_ci] == [0.864, 0.973]
    assert [round(x, 3) for x in bootstrap_interval(s.outcomes, "f1")] == [0.914, 0.982]


def test_the_held_out_intervals_are_too_wide_to_support_a_three_decimal_claim() -> None:
    """116 cases buy roughly a ten-point window. Reporting 0.962 as a fact would be false precision."""
    s = score_cases(TEST_CASES, FUZZY_NAME_THRESHOLD)
    assert s.precision_ci[1] - s.precision_ci[0] > 0.05
    assert s.recall_ci[1] - s.recall_ci[0] > 0.05
    # The interval admits a matcher meaningfully worse than the point estimate, and the doc says so.
    assert s.precision_ci[0] < 0.90
    assert s.recall_ci[0] < 0.90


def test_the_held_out_failures_are_the_five_known_kinds_and_nothing_else() -> None:
    """The error taxonomy in the doc, asserted case by case so a new failure mode cannot arrive quietly."""
    s = score_cases(TEST_CASES, FUZZY_NAME_THRESHOLD)
    by_kind = {
        kind: sorted(o.case.case_id for o in s.errors if o.kind == kind) for kind in ("false_match", "missed_match")
    }
    assert by_kind["false_match"] == [
        "bare_brand/QuantStack",  # legal-form stripping makes "QuantStack GmbH" an exact name match
        "brand_label_only/orion.de",  # brand label on a foreign TLD, no company name to contradict it
        "brand_label_only/terraverde.co.uk",
    ]
    assert by_kind["missed_match"] == [
        "group_suffix/northwind-logistics.example/Northwind Logistics Group",
        "legal_suffix/aurora-labs.example/Aurora Labs BV",  # "B.V." is not stripped, "BV" is
        "legal_suffix/molinari.example/Molinari Impianti SpA",
        "typo_domain_only/kestrel-analytics.example/kestrel-analytcs.example",  # domains are never fuzzy-matched
        "typo_domain_only/terra-verde.example/terra-vrde.example",
    ]
    # No lead was attached to an account when a *different* account was the right answer: every false
    # positive here is a match that should have been an abstention, not a swap between two real accounts.
    assert not [o for o in s.errors if o.kind == "wrong_match"]


def test_matches_the_matcher_would_apply_unsupervised_are_more_precise_than_the_headline() -> None:
    """The number that matters operationally: precision among matches that skip the review queue.

    Two of the three held-out false positives raise `review_required`, so they land in front of a human
    before they reach a rep. Precision on the rest is the rate at which the system silently attaches a lead
    to the wrong company, which is the failure this matcher is built to avoid.
    """
    s = score_cases(TEST_CASES, FUZZY_NAME_THRESHOLD)
    auto = [o for o in s.outcomes if o.predicted is not None and not o.review_required]
    correct = [o for o in auto if o.kind == "true_match"]
    assert (len(correct), len(auto)) == (64, 65)
    assert len(auto) < s.tp + s.fp  # some matches really are being held back for review


def test_the_matcher_errs_toward_missing_a_lead_rather_than_misrouting_one() -> None:
    """The asymmetry the threshold is set for: a wrong account is worse than an unmatched one."""
    for cases in (DEV_CASES, TEST_CASES):
        s = score_cases(cases, FUZZY_NAME_THRESHOLD)
        assert s.precision >= s.recall
        assert s.fp <= s.fn


def test_the_bootstrap_interval_is_reproducible_across_runs() -> None:
    s = score_cases(TEST_CASES, FUZZY_NAME_THRESHOLD)
    assert bootstrap_interval(s.outcomes, "f1") == bootstrap_interval(s.outcomes, "f1")
    lo, hi = bootstrap_interval(s.outcomes, "precision")
    assert lo <= s.precision <= hi
    assert bootstrap_interval((), "f1") == (0.0, 0.0)


def test_lowering_the_threshold_would_buy_false_positives_rather_than_matches() -> None:
    """Checked on development cases only: the reason the bar is where it is, not a held-out result."""
    strict = score_cases(DEV_CASES, 0.87)
    loose = score_cases(DEV_CASES, 0.70)
    assert loose.fp > strict.fp
    assert loose.tp - strict.tp <= loose.fp - strict.fp  # every extra match costs at least one wrong one
