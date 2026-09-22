"""The evaluation maths, checked against cases computed by hand.

A backtest is only worth publishing if the statistics behind it are right, so every function is pinned
to a case small enough to verify on paper.
"""

from __future__ import annotations

import pytest

from gtmos.domain.evaluation import (
    Observation,
    auc_interval,
    evaluate,
    grade_buckets,
    precision_at_k,
    roc_auc,
    score_buckets,
)


def obs(pairs: list[tuple[float, bool]], grade: str = "") -> list[Observation]:
    return [Observation(key=f"a{i}", score=s, outcome=o, grade=grade) for i, (s, o) in enumerate(pairs)]


def test_auc_is_one_when_every_positive_outranks_every_negative():
    assert roc_auc(obs([(10, True), (9, True), (2, False), (1, False)])) == 1.0


def test_auc_is_zero_when_the_ranking_is_exactly_inverted():
    assert roc_auc(obs([(10, False), (9, False), (2, True), (1, True)])) == 0.0


def test_auc_is_half_when_scores_are_all_tied():
    # Every comparison is a tie, so each contributes 0.5 — the definition of "no information".
    assert roc_auc(obs([(5, True), (5, True), (5, False), (5, False)])) == 0.5


def test_auc_counts_ties_as_half_a_win():
    # Pairs: (3,T) beats (1,F) and (2,F); (2,T) ties (2,F) and beats (1,F).
    # Wins = 2 + 0.5 + 1 = 3.5 of 4 comparisons.
    assert roc_auc(obs([(3, True), (2, True), (2, False), (1, False)])) == pytest.approx(3.5 / 4)


def test_auc_is_undefined_without_both_classes():
    assert roc_auc(obs([(3, True), (2, True)])) is None
    assert roc_auc([]) is None


def test_auc_interval_brackets_the_estimate_and_narrows_with_sample_size():
    # The same ranking pattern at two sample sizes: identical AUC, different certainty.
    pattern = [(3.0, True), (2.0, False), (1.0, True), (0.0, False)]
    small, big = obs(pattern), obs(pattern * 150)
    auc_small, auc_big = roc_auc(small), roc_auc(big)
    assert auc_small is not None and auc_big is not None
    assert auc_small == pytest.approx(auc_big)
    wide, narrow = auc_interval(small, auc_small), auc_interval(big, auc_big)
    assert wide[0] <= auc_small <= wide[1]
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_score_buckets_are_equal_count_and_ordered_high_to_low():
    rows = obs([(float(i), i >= 8) for i in range(10)])
    buckets = score_buckets(rows, bins=5)
    assert [b.n for b in buckets] == [2, 2, 2, 2, 2]
    assert buckets[0].label == "Top 20%"
    assert buckets[0].positives == 2 and buckets[-1].positives == 0
    assert buckets[0].score_min == 8.0 and buckets[0].score_max == 9.0


def test_bucket_lift_is_relative_to_the_base_rate():
    # 10 rows, 2 positives → base 20%. The top bin holds both → 100%, a lift of 5.
    buckets = score_buckets(obs([(float(i), i >= 8) for i in range(10)]), bins=5)
    assert buckets[0].rate == 1.0
    assert buckets[0].lift == pytest.approx(5.0)


def test_small_buckets_are_flagged_rather_than_reported_as_fact():
    assert all(b.small_sample for b in score_buckets(obs([(float(i), i > 5) for i in range(10)])))
    big = score_buckets(obs([(float(i), i > 100) for i in range(400)]), bins=2)
    assert not any(b.small_sample for b in big)


def test_precision_at_k_compares_against_shuffling_the_list():
    # 100 accounts, 20 positives, all of them in the top 20 by score.
    rows = obs([(float(i), i >= 80) for i in range(100)])
    at_20 = next(r for r in precision_at_k(rows, ks=(20,)))
    assert at_20["hits"] == 20
    assert at_20["precision"] == 1.0
    assert at_20["random_expected"] == pytest.approx(4.0)  # base rate 20% × 20
    assert at_20["lift"] == pytest.approx(5.0)
    assert at_20["recall"] == 1.0


def test_precision_at_k_skips_k_larger_than_the_population():
    assert precision_at_k(obs([(1.0, True), (0.0, False)]), ks=(50,)) == []


def test_grade_buckets_keep_the_published_order_and_drop_empty_grades():
    rows = [
        *obs([(90, True), (85, True)], grade="A"),
        *obs([(60, False)], grade="C"),
    ]
    assert [b.label for b in grade_buckets(rows)] == ["A", "C"]


def test_evaluate_detects_a_monotonic_ranking_and_warns_on_a_random_one():
    good = evaluate(obs([(float(i), i >= 300) for i in range(400)]), bins=4)
    assert good.monotonic
    assert good.auc == 1.0

    # Alternating outcomes: the score carries no information and the report must say so.
    noise = evaluate(obs([(float(i), i % 2 == 0) for i in range(400)]), bins=4)
    assert noise.auc == pytest.approx(0.5, abs=0.01)
    assert any("not distinguishable from random" in w for w in noise.warnings)


def test_evaluate_warns_when_there_are_too_few_positives_to_conclude_anything():
    ev = evaluate(obs([(float(i), i == 399) for i in range(400)]), bins=4)
    assert any("positive outcomes" in w for w in ev.warnings)


def test_evaluate_handles_an_empty_population_without_dividing_by_zero():
    ev = evaluate([])
    assert ev.n == 0 and ev.base_rate == 0.0 and ev.auc is None
    assert ev.as_dict()["auc"] is None
