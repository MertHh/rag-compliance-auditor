import pytest

from auditor.retrieval.fusion import rrf_fuse


def test_item_in_both_lists_beats_items_in_one():
    fused = rrf_fuse([["a", "b", "c"], ["b", "d"]], k=60)
    assert [item for item, _ in fused] == ["b", "a", "d", "c"]
    assert dict(fused)["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert dict(fused)["a"] == pytest.approx(1 / 61)


def test_ties_keep_first_seen_order():
    fused = rrf_fuse([["a"], ["b"]], k=60)
    assert [item for item, _ in fused] == ["a", "b"]


def test_single_list_keeps_its_order():
    assert [item for item, _ in rrf_fuse([["x", "y", "z"]])] == ["x", "y", "z"]


def test_empty_inputs():
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []
