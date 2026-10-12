import uuid

import pytest

from auditor.index.qdrant_store import QdrantStore
from auditor.index.store import SearchFilter, SparseVec, date_to_int
from auditor.ingestion.chunker import Chunk, PageBox


def _chunk(document_id: str, n: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}:{n}")),
        document_id=document_id,
        text=text,
        char_start=n * 10,
        char_end=n * 10 + len(text),
        pages=[1],
        bboxes=[PageBox(1, (1.0, 2.0, 3.0, 4.0))],
        section_title="Title",
        section_path=f"{n}",
        parent_id=f"{document_id}:0-100",
        parent_start=0,
        parent_end=100,
        parent_section_path="1",
        context_prefix="ctx",
    )


@pytest.fixture
def store():
    s = QdrantStore.in_memory()
    s.ensure_collection(4)
    s.upsert(
        [_chunk("docA", 0, "alpha"), _chunk("docA", 1, "beta")],
        [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
        [SparseVec([1], [1.0]), SparseVec([2], [1.0])],
        {"doc_type": "NDA", "jurisdiction": "NY", "date": "2023-05-01"},
    )
    s.upsert(
        [_chunk("docB", 0, "gamma")],
        [[0.9, 0.1, 0.0, 0.0]],
        [SparseVec([1, 3], [0.5, 1.0])],
        {"doc_type": "MSA", "jurisdiction": "CA", "date": "2024-02-10"},
    )
    return s


def test_date_to_int():
    assert date_to_int("2023-05-01") == 20230501
    assert date_to_int(None) is None
    assert date_to_int("") is None


def test_dense_search_orders_by_similarity(store):
    hits = store.search_dense([1.0, 0.0, 0.0, 0.0], limit=3)
    assert [h.payload["text"] for h in hits] == ["alpha", "gamma", "beta"]
    assert hits[0].score >= hits[1].score >= hits[2].score


def test_sparse_search_returns_only_matching_terms(store):
    hits = store.search_sparse(SparseVec([3], [1.0]), limit=5)
    assert [h.payload["text"] for h in hits] == ["gamma"]


def test_payload_roundtrip(store):
    hit = store.search_dense([1.0, 0.0, 0.0, 0.0], limit=1)[0]
    p = hit.payload
    assert hit.chunk_id == str(uuid.uuid5(uuid.NAMESPACE_URL, "docA:0"))
    assert p["document_id"] == "docA"
    assert p["bboxes"] == [{"page": 1, "bbox": [1.0, 2.0, 3.0, 4.0]}]
    assert p["pages"] == [1]
    assert (p["parent_id"], p["parent_start"], p["parent_end"]) == ("docA:0-100", 0, 100)
    assert p["parent_section_path"] == "1"
    assert p["context_prefix"] == "ctx"
    assert (p["doc_type"], p["jurisdiction"], p["date"], p["date_int"]) == ("NDA", "NY", "2023-05-01", 20230501)


def test_limit_is_respected(store):
    assert len(store.search_dense([1.0, 0.0, 0.0, 0.0], limit=2)) == 2


@pytest.mark.parametrize("flt,expected", [
    (SearchFilter(document_ids=["docB"]), {"gamma"}),
    (SearchFilter(doc_types=["NDA"]), {"alpha", "beta"}),
    (SearchFilter(jurisdictions=["CA", "TX"]), {"gamma"}),
    (SearchFilter(date_from="2024-01-01"), {"gamma"}),
    (SearchFilter(date_to="2023-12-31"), {"alpha", "beta"}),
    (SearchFilter(date_from="2023-05-01", date_to="2023-05-01"), {"alpha", "beta"}),
    (SearchFilter(doc_types=["NDA"], document_ids=["docB"]), set()),
    (SearchFilter(document_ids=["nope"]), set()),
])
def test_filters(store, flt, expected):
    dense = store.search_dense([1.0, 1.0, 0.0, 0.0], limit=10, flt=flt)
    assert {h.payload["text"] for h in dense} == expected
    sparse = store.search_sparse(SparseVec([1, 2, 3], [1.0, 1.0, 1.0]), limit=10, flt=flt)
    assert {h.payload["text"] for h in sparse} == expected


def test_has_and_delete_document(store):
    assert store.has_document("docA") is True
    store.delete_document("docA")
    assert store.has_document("docA") is False
    assert {h.payload["text"] for h in store.search_dense([1.0, 1.0, 0.0, 0.0], limit=10)} == {"gamma"}


def test_set_document_metadata_updates_filter_fields(store):
    store.set_document_metadata("docA", {"doc_type": "DPA", "jurisdiction": "DE", "date": "2025-01-15"})
    hits = store.search_dense([1.0, 1.0, 0.0, 0.0], limit=10, flt=SearchFilter(doc_types=["DPA"]))
    assert {h.payload["text"] for h in hits} == {"alpha", "beta"}
    assert hits[0].payload["date_int"] == 20250115
    assert hits[0].payload["text"] in {"alpha", "beta"}


def test_empty_sparse_query_returns_nothing(store):
    assert store.search_sparse(SparseVec([], []), limit=5) == []


def test_ensure_collection_is_idempotent(store):
    store.ensure_collection(4)
    assert store.has_document("docA")


def test_missing_collection_behaves_as_empty():
    s = QdrantStore.in_memory()
    assert s.search_dense([1.0, 0.0, 0.0, 0.0], limit=5) == []
    assert s.search_sparse(SparseVec([1], [1.0]), limit=5) == []
    assert s.has_document("docA") is False
    s.delete_document("docA")
    s.set_document_metadata("docA", {"doc_type": "NDA"})
