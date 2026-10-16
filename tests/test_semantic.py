from fakes import FakeEmbedder, FakeSparseEncoder

from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.indexer import Indexer
from auditor.ingestion.parser import parse_text
from auditor.ingestion.semantic import build_semantic_chunks, percentile, sentence_spans
from auditor.storage.docstore import DocumentStore
from auditor.tokens import count_tokens

TEXT = (
    "Liability fees cap liability fees. Liability cap fees total liability. "
    "The liability fees cap applies.\n\n"
    "Governing law New York courts. New York law governs courts. Courts of New York law apply."
)


def test_sentence_spans_cover_sentences():
    spans = sentence_spans(TEXT, 400)
    assert [TEXT[s:e] for s, e in spans][:2] == ["Liability fees cap liability fees.",
                                                 "Liability cap fees total liability."]
    assert len(spans) == 6


def test_percentile():
    assert percentile([0.1, 0.2, 0.3, 0.4, 0.5], 100) == 0.5
    assert percentile([0.1, 0.2, 0.3, 0.4, 0.5], 60) == 0.3
    assert percentile([0.4], 90) == 0.4


def test_splits_where_the_topic_changes():
    doc = parse_text(TEXT, "c.txt")
    chunks = build_semantic_chunks(doc, FakeEmbedder(), breakpoint_percentile=100)
    assert len(chunks) == 2
    assert chunks[0].text.endswith("The liability fees cap applies.")
    assert chunks[1].text.startswith("Governing law New York courts.")
    for chunk in chunks:
        assert doc.text[chunk.char_start:chunk.char_end] == chunk.text
        assert (chunk.parent_start, chunk.parent_end) == (chunk.char_start, chunk.char_end)
        assert chunk.parent_id == f"{doc.document_id}:{chunk.char_start}-{chunk.char_end}"


def test_token_limit_is_respected():
    doc = parse_text(TEXT, "c.txt")
    chunks = build_semantic_chunks(doc, FakeEmbedder(), max_tokens=8, breakpoint_percentile=100)
    assert len(chunks) >= 6
    assert all(count_tokens(chunk.text) <= 8 for chunk in chunks)


def test_empty_document_has_no_chunks():
    assert build_semantic_chunks(parse_text("  \n ", "e.txt"), FakeEmbedder()) == []


def test_indexer_uses_the_given_chunker(tmp_path):
    embedder = FakeEmbedder()
    chunker = lambda doc: build_semantic_chunks(doc, embedder, breakpoint_percentile=100)
    indexer = Indexer(QdrantStore.in_memory(), embedder, FakeSparseEncoder(),
                      DocumentStore(tmp_path / "docs"), chunker=chunker)
    assert indexer.ingest_text(TEXT, "c.txt").chunk_count == 2
