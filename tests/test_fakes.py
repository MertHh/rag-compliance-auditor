import math

from fakes import FakeEmbedder, FakeReranker, FakeSparseEncoder


def test_fake_embedder_is_deterministic_and_normalized():
    e = FakeEmbedder()
    v = e.embed_query("liability cap")
    assert len(v) == e.dim == 64
    assert math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-6)
    assert e.embed_documents(["liability cap"]) == [v]


def test_fake_embedder_similar_texts_are_closer():
    e = FakeEmbedder()
    q = e.embed_query("liability cap")
    near = e.embed_query("the liability cap applies")
    far = e.embed_query("governing law of new york")
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    assert dot(q, near) > dot(q, far)


def test_fake_sparse_encoder_shares_indices_for_shared_words():
    s = FakeSparseEncoder()
    q = s.encode_query("liability")
    d = s.encode_documents(["liability liability cap"])[0]
    assert set(q.indices) <= set(d.indices)
    assert max(d.values) == 2.0
    assert s.encode_query("   ").indices == []


def test_fake_reranker_scores_query_word_overlap():
    r = FakeReranker()
    assert r.score("aggregate liability fees", ["aggregate liability of fees", "liability", "nothing"]) == [1.0, 1 / 3, 0.0]
    assert r.score("x", []) == []
