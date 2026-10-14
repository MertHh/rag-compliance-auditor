import pytest
from fakes import FakeEmbedder, FakeSparseEncoder

from auditor.index.qdrant_store import QdrantStore
from auditor.index.store import SearchFilter
from auditor.ingestion.indexer import EmptyDocumentError, Indexer
from auditor.storage.docstore import DocumentStore


class RecordingEmbedder(FakeEmbedder):
    def __init__(self):
        self.seen: list[str] = []

    def embed_documents(self, texts):
        self.seen.extend(texts)
        return super().embed_documents(texts)


@pytest.fixture
def parts(tmp_path):
    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder = RecordingEmbedder()
    return store, docstore, embedder


def _indexer(parts, **kwargs):
    store, docstore, embedder = parts
    return Indexer(store, embedder, FakeSparseEncoder(), docstore, **kwargs)


def test_ingest_text_indexes_chunks_and_saves_document(parts, sample_contract):
    store, docstore, embedder = parts
    result = _indexer(parts).ingest_text(sample_contract, "msa.txt")
    assert result.already_indexed is False
    assert result.chunk_count == 12
    assert store.has_document(result.document_id)
    assert docstore.load(result.document_id).text == sample_contract
    assert docstore.metadata(result.document_id) == {
        "filename": "msa.txt", "doc_type": None, "date": None,
        "parties": [], "jurisdiction": None,
    }
    hits = store.search_dense(embedder.embed_query("aggregate liability"), limit=30)
    assert len(hits) == 12


def test_reingesting_same_content_is_a_no_op(parts, sample_contract):
    store, _, embedder = parts
    indexer = _indexer(parts)
    first = indexer.ingest_text(sample_contract, "msa.txt")
    seen = len(embedder.seen)
    second = indexer.ingest_text(sample_contract, "renamed.txt")
    assert second.document_id == first.document_id
    assert second.already_indexed is True
    assert second.chunk_count == 0
    assert len(embedder.seen) == seen
    assert len(store.search_dense(embedder.embed_query("liability"), limit=100)) == 12


def test_metadata_is_stored_and_filterable(parts, sample_contract):
    store, docstore, embedder = parts
    meta = {"doc_type": "MSA", "jurisdiction": "NY", "date": "2023-05-01", "parties": ["Acme", "Beta"]}
    result = _indexer(parts).ingest_text(sample_contract, "msa.txt", metadata=meta)
    assert docstore.metadata(result.document_id) == {"filename": "msa.txt", **meta}
    query = embedder.embed_query("liability")
    assert store.search_dense(query, limit=5, flt=SearchFilter(doc_types=["MSA"]))
    assert store.search_dense(query, limit=5, flt=SearchFilter(doc_types=["NDA"])) == []


def test_ingest_pdf_keeps_the_pdf_and_page_numbers(parts, make_pdf, tmp_path):
    store, docstore, embedder = parts
    path = make_pdf(tmp_path / "c.pdf", [
        [("1. Definitions", 11),
         ("Services means the consulting services described in Exhibit A.", 11)],
        [("2. Liability", 11),
         ("The total liability shall not exceed the fees paid in twelve months.", 11)],
    ])
    result = _indexer(parts).ingest_pdf(path)
    assert result.chunk_count == 2
    assert docstore.pdf_path(result.document_id).read_bytes() == path.read_bytes()
    hit = store.search_dense(embedder.embed_query("total liability fees"), limit=1)[0]
    assert hit.payload["pages"] == [2]
    assert hit.payload["bboxes"][0]["page"] == 2


def test_contextualizer_prefixes_embedding_text_only(parts, sample_contract):
    store, _, embedder = parts
    indexer = _indexer(parts, contextualizer=lambda doc, chunk: f"From {doc.filename}.")
    indexer.ingest_text(sample_contract, "msa.txt")
    assert all(text.startswith("From msa.txt.\n\n") for text in embedder.seen)
    hit = store.search_dense(embedder.embed_query("liability"), limit=1)[0]
    assert hit.payload["context_prefix"] == "From msa.txt."
    assert not hit.payload["text"].startswith("From msa.txt.")


def test_chunk_limits_are_passed_through(parts):
    result = _indexer(parts, max_child_tokens=100).ingest_text(" ".join(["tok"] * 500), "t.txt")
    assert result.chunk_count == 5


def test_empty_document_raises_and_stores_nothing(parts):
    store, docstore, _ = parts
    with pytest.raises(EmptyDocumentError):
        _indexer(parts).ingest_text("  \n \n", "empty.txt")
    assert docstore.list_ids() == []


def test_failed_docstore_save_leaves_no_vectors_behind(parts, sample_contract, monkeypatch):
    from auditor.ingestion.parser import parse_text

    store, docstore, _ = parts

    def disk_full(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(docstore, "save", disk_full)
    with pytest.raises(OSError):
        _indexer(parts).ingest_text(sample_contract, "msa.txt")
    assert store.has_document(parse_text(sample_contract, "msa.txt").document_id) is False


def test_is_indexed(parts, sample_contract):
    from auditor.ingestion.parser import parse_text

    indexer = _indexer(parts)
    document_id = parse_text(sample_contract, "c.txt").document_id
    assert indexer.is_indexed(document_id) is False
    indexer.ingest_text(sample_contract, "c.txt")
    assert indexer.is_indexed(document_id) is True


def test_user_metadata_none_does_not_erase_extracted_fields(parts, sample_contract):
    _, docstore, _ = parts
    result = _indexer(parts).ingest_text(
        sample_contract, "c.txt", {"doc_type": None, "jurisdiction": "Delaware"},
        extract_metadata=lambda doc: {"doc_type": "Services Agreement", "jurisdiction": "New York"},
    )
    meta = docstore.metadata(result.document_id)
    assert meta["doc_type"] == "Services Agreement"
    assert meta["jurisdiction"] == "Delaware"
