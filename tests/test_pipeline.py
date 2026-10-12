import pytest
from fakes import FakeEmbedder, FakeReranker, FakeSparseEncoder

from auditor.index.qdrant_store import QdrantStore
from auditor.index.store import SearchFilter
from auditor.ingestion.indexer import Indexer
from auditor.retrieval.config import RetrievalConfig
from auditor.retrieval.pipeline import Retriever
from auditor.storage.docstore import DocumentStore

OTHER_CONTRACT = """1. Confidentiality
1.1 Each party shall keep the other party's information confidential for five years.

2. Liability
2.1 The aggregate liability of the vendor is limited to the fees paid."""


class CountingReranker(FakeReranker):
    def __init__(self):
        self.calls = 0

    def score(self, query, texts):
        self.calls += 1
        return super().score(query, texts)


@pytest.fixture
def env(tmp_path, sample_contract):
    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse, reranker = FakeEmbedder(), FakeSparseEncoder(), CountingReranker()
    indexer = Indexer(store, embedder, sparse, docstore)
    first = indexer.ingest_text(sample_contract, "msa.txt", {"doc_type": "MSA"})
    second = indexer.ingest_text(OTHER_CONTRACT, "nda.txt", {"doc_type": "NDA"})
    retriever = Retriever(store, embedder, sparse, reranker, docstore)
    return retriever, first.document_id, second.document_id, reranker


def test_defaults():
    c = RetrievalConfig()
    assert (c.mode, c.rerank, c.candidate_k, c.final_k) == ("hybrid", True, 30, 5)


def test_hybrid_rerank_puts_best_match_first_with_all_stage_scores(env):
    retriever, msa, _, _ = env
    result = retriever.search("total aggregate liability twelve months", flt=SearchFilter(document_ids=[msa]))
    assert result.insufficient_evidence is False
    assert len(result.chunks) == 5
    top = result.chunks[0]
    assert top.section_path == "3 > 3.1"
    assert top.document_id == msa
    s = top.scores
    assert s.final_rank == 1
    assert s.bm25_rank is not None and s.bm25_score is not None
    assert s.dense_rank is not None and s.dense_score is not None
    assert s.rrf_score is not None
    assert s.rerank_score == 1.0
    assert [c.scores.final_rank for c in result.chunks] == [1, 2, 3, 4, 5]
    for chunk in result.chunks:
        assert chunk.scores.rank_change == chunk.scores.fused_rank - chunk.scores.final_rank
    scores = [c.scores.rerank_score for c in result.chunks]
    assert scores == sorted(scores, reverse=True)


def test_bm25_mode_has_no_dense_or_rrf_scores(env):
    retriever, _, _, _ = env
    result = retriever.search("aggregate liability", RetrievalConfig(mode="bm25", rerank=False))
    assert result.chunks
    for chunk in result.chunks:
        s = chunk.scores
        assert s.bm25_rank == s.fused_rank == s.final_rank
        assert s.dense_rank is None and s.dense_score is None and s.rrf_score is None
        assert s.rerank_score is None and s.rank_change == 0


def test_dense_mode_has_no_bm25_scores(env):
    retriever, _, _, _ = env
    result = retriever.search("aggregate liability", RetrievalConfig(mode="dense", rerank=False))
    assert result.chunks
    assert all(c.scores.bm25_rank is None and c.scores.dense_rank == c.scores.fused_rank
               for c in result.chunks)


def test_rerank_off_skips_reranker_and_never_flags_non_empty_results(env):
    retriever, _, _, reranker = env
    result = retriever.search("zebra giraffe", RetrievalConfig(mode="dense", rerank=False))
    assert reranker.calls == 0
    assert result.chunks
    assert result.insufficient_evidence is False


def test_final_k_and_candidate_k_are_respected(env):
    retriever, _, _, _ = env
    result = retriever.search("liability", RetrievalConfig(candidate_k=4, final_k=2))
    assert len(result.chunks) == 2
    assert all(c.scores.fused_rank <= 4 for c in result.chunks)


def test_low_rerank_score_flags_insufficient_evidence(env):
    retriever, _, _, _ = env
    result = retriever.search("zebra giraffe")
    assert result.insufficient_evidence is True
    result = retriever.search("zebra giraffe", RetrievalConfig(min_rerank_score=0.0))
    assert result.insufficient_evidence is False


def test_filter_limits_results_to_matching_documents(env):
    retriever, _, nda, _ = env
    result = retriever.search("aggregate liability fees", flt=SearchFilter(doc_types=["NDA"]))
    assert result.chunks
    assert {c.document_id for c in result.chunks} == {nda}


def test_parents_are_expanded_and_deduplicated(env):
    retriever, msa, _, _ = env
    result = retriever.search("liability damages", flt=SearchFilter(document_ids=[msa]))
    parent_ids = [p.parent_id for p in result.parents]
    assert len(parent_ids) == len(set(parent_ids))
    assert {c.chunk_id for c in result.chunks} == {cid for p in result.parents for cid in p.chunk_ids}
    liability = next(p for p in result.parents if p.section_path == "3")
    assert liability.text.startswith("3. Limitation of Liability")
    assert "3.1 The total aggregate liability" in liability.text
    assert "3.2 Neither party" in liability.text
    assert len(liability.chunk_ids) >= 2
    assert result.parents[0].parent_id == result.chunks[0].parent_id


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_blank_query_returns_empty_result_without_calling_models(env, query):
    retriever, _, _, reranker = env
    result = retriever.search(query)
    assert result.chunks == [] and result.parents == []
    assert result.insufficient_evidence is True
    assert reranker.calls == 0


def test_filter_matching_nothing_returns_empty_result(env):
    retriever, _, _, _ = env
    result = retriever.search("liability", flt=SearchFilter(document_ids=["no-such-document"]))
    assert result.chunks == [] and result.parents == []
    assert result.insufficient_evidence is True


def test_search_before_anything_is_indexed(tmp_path):
    retriever = Retriever(QdrantStore.in_memory(), FakeEmbedder(), FakeSparseEncoder(),
                          FakeReranker(), DocumentStore(tmp_path / "docs"))
    result = retriever.search("liability")
    assert result.chunks == []
    assert result.insufficient_evidence is True


def test_missing_document_text_falls_back_to_chunk_text(tmp_path, sample_contract):
    store = QdrantStore.in_memory()
    embedder, sparse = FakeEmbedder(), FakeSparseEncoder()
    Indexer(store, embedder, sparse, DocumentStore(tmp_path / "a")).ingest_text(sample_contract, "msa.txt")
    retriever = Retriever(store, embedder, sparse, FakeReranker(), DocumentStore(tmp_path / "empty"))
    result = retriever.search("total aggregate liability twelve months")
    top = result.chunks[0]
    assert top.section_path == "3 > 3.1"
    parent = result.parents[0]
    assert parent.text == top.text
    assert (parent.char_start, parent.char_end) == (top.char_start, top.char_end)
