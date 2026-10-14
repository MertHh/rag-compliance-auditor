import pytest
from fakes import FakeEmbedder, FakeLLM, FakeReranker, FakeSparseEncoder

from auditor.index.qdrant_store import QdrantStore
from auditor.index.store import SearchFilter
from auditor.ingestion.indexer import Indexer
from auditor.llm.base import LLMError
from auditor.qa.answer import NOT_FOUND_MESSAGE, QAOutput, QuestionAnswerer
from auditor.retrieval.pipeline import Retriever
from auditor.storage.docstore import DocumentStore

OTHER = """1. Confidentiality
1.1 Each party shall keep the other party's information confidential for five years.

2. Liability
2.1 The aggregate liability of the vendor is limited to the fees paid."""

QUOTE = ("The total aggregate liability of either party shall not exceed the fees paid in the "
         "twelve months preceding the claim.")


@pytest.fixture
def env(tmp_path, sample_contract):
    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse = FakeEmbedder(), FakeSparseEncoder()
    indexer = Indexer(store, embedder, sparse, docstore)
    msa = indexer.ingest_text(sample_contract, "msa.txt").document_id
    nda = indexer.ingest_text(OTHER, "nda.txt").document_id
    return Retriever(store, embedder, sparse, FakeReranker(), docstore), docstore, msa, nda


def _ask(env, llm, question, flt=None):
    retriever, docstore, _, _ = env
    return QuestionAnswerer(retriever, docstore, llm).ask(question, flt)


def test_answer_with_verified_quote(env):
    llm = FakeLLM({"QAOutput": QAOutput(answer=" Liability is capped at twelve months of fees. ", quotes=[QUOTE])})
    answer = _ask(env, llm, "total aggregate liability fees paid")
    assert answer.found is True
    assert answer.answer == "Liability is capped at twelve months of fees."
    assert answer.message is None
    [citation] = answer.citations
    assert citation.document_id == env[2]
    assert answer.model == "fake-small"
    assert answer.usage.input_tokens == 100
    assert llm.calls[0][1] == "small"
    assert "Question: total aggregate liability fees paid" in llm.calls[0][2]


def test_no_evidence_skips_the_llm(env):
    llm = FakeLLM()
    answer = _ask(env, llm, "zebra quantum")
    assert llm.calls == []
    assert answer.found is False
    assert answer.answer is None
    assert answer.message == NOT_FOUND_MESSAGE
    assert answer.passages


def test_unverified_quote_hides_the_answer(env):
    llm = FakeLLM({"QAOutput": QAOutput(answer="Unlimited.", quotes=["Liability is unlimited for every claim."])})
    answer = _ask(env, llm, "total aggregate liability fees paid")
    assert answer.found is False
    assert answer.answer is None
    assert answer.message == NOT_FOUND_MESSAGE
    assert answer.model == "fake-small"


def test_empty_answer_is_not_found(env):
    llm = FakeLLM({"QAOutput": QAOutput(answer="", quotes=[])})
    assert _ask(env, llm, "total aggregate liability fees paid").found is False


def test_filter_limits_passages_and_citations(env):
    _, _, _, nda = env
    quote = "The aggregate liability of the vendor is limited to the fees paid."
    llm = FakeLLM({"QAOutput": QAOutput(answer="Limited to fees.", quotes=[quote, QUOTE])})
    answer = _ask(env, llm, "aggregate liability fees paid", SearchFilter(document_ids=[nda]))
    assert {p.document_id for p in answer.passages} == {nda}
    assert [c.document_id for c in answer.citations] == [nda]


def test_llm_failure_propagates(env):
    llm = FakeLLM({"QAOutput": LLMError("down")})
    with pytest.raises(LLMError):
        _ask(env, llm, "total aggregate liability fees paid")
