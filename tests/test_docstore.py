import pytest

from auditor.ingestion.parser import Line, ParsedDocument, parse_text
from auditor.storage.docstore import DocumentNotFound, DocumentStore


def test_save_and_load_roundtrip_from_disk(tmp_path):
    doc = ParsedDocument(
        document_id="abc",
        filename="c.pdf",
        text="Hello\nİşbu sözleşme",
        lines=[Line("Hello", 1, (1.0, 2.0, 3.0, 4.0), 11.0, 0, 5),
               Line("İşbu sözleşme", 2, (5.0, 6.0, 7.0, 8.0), 11.0, 6, 19)],
        page_count=2,
    )
    DocumentStore(tmp_path).save(doc, {"filename": "c.pdf"})
    loaded = DocumentStore(tmp_path).load("abc")
    assert loaded == doc
    assert isinstance(loaded.lines[0].bbox, tuple)


def test_exists_and_list_ids(tmp_path):
    store = DocumentStore(tmp_path)
    assert store.exists("x") is False
    assert store.list_ids() == []
    b = parse_text("b", "b.txt")
    a = parse_text("a", "a.txt")
    store.save(b, {})
    store.save(a, {})
    assert store.exists(a.document_id)
    assert store.list_ids() == sorted([a.document_id, b.document_id])


def test_load_missing_raises(tmp_path):
    store = DocumentStore(tmp_path)
    with pytest.raises(DocumentNotFound):
        store.load("missing")
    with pytest.raises(DocumentNotFound):
        store.metadata("missing")


def test_metadata_update_merges_and_persists(tmp_path):
    doc = parse_text("a", "a.txt")
    DocumentStore(tmp_path).save(doc, {"filename": "a.txt", "doc_type": None})
    merged = DocumentStore(tmp_path).update_metadata(doc.document_id, {"doc_type": "NDA"})
    assert merged == {"filename": "a.txt", "doc_type": "NDA"}
    assert DocumentStore(tmp_path).metadata(doc.document_id) == merged


def test_pdf_bytes_are_kept(tmp_path):
    store = DocumentStore(tmp_path)
    with_pdf = parse_text("a", "a.pdf")
    without_pdf = parse_text("b", "b.txt")
    store.save(with_pdf, {}, source_pdf=b"%PDF-bytes")
    store.save(without_pdf, {})
    assert store.pdf_path(with_pdf.document_id).read_bytes() == b"%PDF-bytes"
    assert store.pdf_path(without_pdf.document_id) is None


def test_root_directory_is_created(tmp_path):
    root = tmp_path / "nested" / "docs"
    DocumentStore(root)
    assert root.is_dir()
