import pytest

from auditor.bench.budget import Budget, BudgetExceeded
from auditor.bench.metrics import (
    PRF,
    absence_prf,
    best_f1_threshold,
    citation_hits,
    first_hit,
    mrr,
    overlaps,
    prf,
    recall_at,
    threshold_for_present_recall,
)


def test_overlaps_is_strict_on_touching_edges():
    assert overlaps((0, 10), (5, 20))
    assert overlaps((5, 6), (0, 10))
    assert not overlaps((0, 10), (10, 20))


def test_first_hit_and_rank_metrics():
    gold = [(100, 150)]
    assert first_hit([(0, 50), (140, 200), (100, 120)], gold) == 2
    assert first_hit([(0, 50)], gold) is None
    assert first_hit([(0, 50)], []) is None
    ranks = [1, 3, None, 30]
    assert recall_at(ranks, 1) == 0.25
    assert recall_at(ranks, 5) == 0.5
    assert recall_at(ranks, 30) == 0.75
    assert mrr(ranks) == pytest.approx((1 + 1 / 3 + 1 / 30) / 4)
    assert recall_at([], 5) == 0.0 and mrr([]) == 0.0


def test_prf_handles_zero_division():
    assert prf(3, 1, 2) == PRF(0.75, 0.6, pytest.approx(2 * 0.75 * 0.6 / 1.35), 3, 1, 2)
    assert prf(0, 0, 0) == PRF(0.0, 0.0, 0.0, 0, 0, 0)


PAIRS = [(0.01, False), (0.02, False), (0.03, True), (0.20, False), (0.50, True), (0.90, True)]


def test_absence_prf_counts_missing_as_positive():
    result = absence_prf(PAIRS, 0.05)
    assert (result.tp, result.fp, result.fn) == (2, 1, 1)


def test_best_f1_threshold_sweeps_every_score():
    threshold, result = best_f1_threshold(PAIRS)
    brute = max((absence_prf(PAIRS, t).f1, -t) for t in [s for s, _ in PAIRS] + [1.0])
    assert result.f1 == pytest.approx(brute[0])
    assert absence_prf(PAIRS, threshold).f1 == pytest.approx(result.f1)


def test_threshold_for_present_recall():
    present = [(s, True) for s in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)]
    assert threshold_for_present_recall(present + [(0.0, False)], 0.9) == 0.2
    assert threshold_for_present_recall(present, 1.0) == 0.1
    assert threshold_for_present_recall([(0.3, False)], 0.95) == 0.0


def test_citation_hits():
    assert citation_hits([(0, 5), (100, 110), (200, 210)], [(103, 300)]) == 2


def test_budget_projects_from_average_and_stops():
    budget = Budget(max_usd=1.0)
    budget.check(remaining=10)
    budget.record(0.15)
    assert budget.projected(remaining=5) == pytest.approx(0.9)
    budget.check(remaining=5)
    with pytest.raises(BudgetExceeded, match=r"\$1.00 cap"):
        budget.check(remaining=6)
