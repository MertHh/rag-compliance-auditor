import pytest

pytestmark = pytest.mark.slow


def test_bge_m3_embedder_dimensions_and_similarity():
    from auditor.index.embedder import BgeM3Embedder

    e = BgeM3Embedder()
    assert e.dim == 1024
    q = e.embed_query("limitation of liability")
    docs = e.embed_documents([
        "The total aggregate liability of either party shall not exceed the fees paid.",
        "This Agreement is governed by the laws of the State of New York.",
    ])
    assert len(q) == 1024 and len(docs) == 2
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    assert dot(q, docs[0]) > dot(q, docs[1])


def test_bm25_sparse_encoder_matches_shared_terms():
    from auditor.index.embedder import Bm25SparseEncoder

    s = Bm25SparseEncoder()
    docs = s.encode_documents(["liability cap applies", "governing law"])
    q = s.encode_query("liability")
    assert len(docs) == 2
    assert set(q.indices) & set(docs[0].indices)
    assert not set(q.indices) & set(docs[1].indices)
    assert all(isinstance(i, int) for i in q.indices)
    assert all(isinstance(v, float) for v in docs[0].values)


def test_bge_reranker_scores_are_probabilities_in_input_order():
    from auditor.retrieval.reranker import BgeReranker

    r = BgeReranker()
    scores = r.score("What is the liability cap?", [
        "This Agreement is governed by the laws of the State of New York.",
        "The total aggregate liability of either party shall not exceed the fees paid.",
    ])
    assert len(scores) == 2
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores[1] > scores[0]
    assert r.score("anything", []) == []
