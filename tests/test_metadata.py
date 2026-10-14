from fakes import FakeEmbedder, FakeLLM, FakeSparseEncoder

from auditor.index.qdrant_store import QdrantStore
from auditor.index.store import SearchFilter
from auditor.ingestion.indexer import Indexer
from auditor.ingestion.metadata import DocumentMetadata, MetadataExtractor
from auditor.ingestion.parser import parse_pdf, parse_text
from auditor.llm.base import LLMError
from auditor.storage.docstore import DocumentStore


def test_extracted_values_are_cleaned(sample_contract):
    llm = FakeLLM({"DocumentMetadata": DocumentMetadata(
        doc_type="  Master Services Agreement ", date="March 1st, 2024",
        parties=["Acme Corp", " Acme Corp ", "", "Beta LLC"], jurisdiction="  ")})
    meta = MetadataExtractor(llm)(parse_text(sample_contract, "msa.txt"))
    assert meta == {"doc_type": "Master Services Agreement", "parties": ["Acme Corp", "Beta LLC"]}
    assert llm.calls[0][1] == "small"
    assert "MASTER SERVICES AGREEMENT" in llm.calls[0][2]


def test_iso_date_is_kept(sample_contract):
    llm = FakeLLM({"DocumentMetadata": DocumentMetadata(
        doc_type=None, date="2024-03-01", parties=[], jurisdiction="New York")})
    assert MetadataExtractor(llm)(parse_text(sample_contract, "msa.txt")) == {
        "date": "2024-03-01", "jurisdiction": "New York"}


def test_llm_failure_gives_empty_metadata(sample_contract):
    llm = FakeLLM({"DocumentMetadata": LLMError("down")})
    assert MetadataExtractor(llm)(parse_text(sample_contract, "msa.txt")) == {}


def test_only_first_two_pages_are_sent(make_pdf, tmp_path):
    path = make_pdf(tmp_path / "c.pdf", [
        [("MASTER SERVICES AGREEMENT between Acme Corp and Beta LLC, entered into March 1, 2024", 11)],
        [("1. Term", 11), ("This agreement lasts two years from signing.", 11)],
        [("SECRET PAGE THREE text that must not be sent", 11)],
    ])
    llm = FakeLLM({"DocumentMetadata": DocumentMetadata(doc_type=None, date=None, parties=[], jurisdiction=None)})
    MetadataExtractor(llm)(parse_pdf(path))
    prompt = llm.calls[0][2]
    assert "MASTER SERVICES AGREEMENT" in prompt and "two years" in prompt
    assert "SECRET PAGE THREE" not in prompt


def test_indexer_merges_extracted_under_user_metadata(tmp_path, sample_contract):
    store, docstore = QdrantStore.in_memory(), DocumentStore(tmp_path / "docs")
    indexer = Indexer(store, FakeEmbedder(), FakeSparseEncoder(), docstore)
    calls = []

    def extract(doc):
        calls.append(doc.document_id)
        return {"doc_type": "MSA", "jurisdiction": "New York"}

    result = indexer.ingest_text(sample_contract, "msa.txt", {"jurisdiction": "Delaware"},
                                 extract_metadata=extract)
    meta = docstore.metadata(result.document_id)
    assert (meta["doc_type"], meta["jurisdiction"], meta["filename"]) == ("MSA", "Delaware", "msa.txt")
    hits = store.search_dense(FakeEmbedder().embed_query("liability"), 5, SearchFilter(doc_types=["MSA"]))
    assert hits

    again = indexer.ingest_text(sample_contract, "msa.txt", extract_metadata=extract)
    assert again.already_indexed is True
    assert calls == [result.document_id]
