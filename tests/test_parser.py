import pytest

from auditor.ingestion.parser import (
    InvalidPdfError,
    ScannedPdfError,
    parse_pdf,
    parse_text,
)

PAGES = [
    [("MASTER SERVICES AGREEMENT", 16),
     ("1. Definitions and interpretation of this agreement", 11)],
    [("2. Term and termination of the services agreement here", 11)],
]


def test_parse_text_keeps_lines_and_offsets():
    doc = parse_text("First line\n\nSecond line", "a.txt")
    assert doc.text == "First line\n\nSecond line"
    assert [l.text for l in doc.lines] == ["First line", "", "Second line"]
    for line in doc.lines:
        assert doc.text[line.char_start:line.char_end] == line.text
        assert line.page is None and line.bbox is None
    assert doc.page_count == 0
    assert len(doc.document_id) == 64
    assert doc.filename == "a.txt"


def test_parse_text_normalizes_windows_newlines():
    assert parse_text("a\r\nb", "a.txt").text == "a\nb"


def test_parse_text_id_depends_on_content():
    assert parse_text("a", "x.txt").document_id == parse_text("a", "y.txt").document_id
    assert parse_text("a", "x.txt").document_id != parse_text("b", "x.txt").document_id


def test_parse_pdf_lines_carry_page_bbox_and_font(make_pdf, tmp_path):
    doc = parse_pdf(make_pdf(tmp_path / "c.pdf", PAGES))
    lines = [l for l in doc.lines if l.text]
    assert [l.text for l in lines] == [
        "MASTER SERVICES AGREEMENT",
        "1. Definitions and interpretation of this agreement",
        "2. Term and termination of the services agreement here",
    ]
    assert [l.page for l in lines] == [1, 1, 2]
    assert lines[0].font_size == pytest.approx(16, abs=0.1)
    assert lines[1].font_size == pytest.approx(11, abs=0.1)
    assert all(len(l.bbox) == 4 for l in lines)
    assert doc.page_count == 2
    assert doc.filename == "c.pdf"


def test_parse_pdf_text_matches_line_offsets(make_pdf, tmp_path):
    doc = parse_pdf(make_pdf(tmp_path / "c.pdf", PAGES))
    assert doc.text == "\n".join(l.text for l in doc.lines)
    for line in doc.lines:
        assert doc.text[line.char_start:line.char_end] == line.text


def test_parse_pdf_id_is_stable_across_filenames(make_pdf, tmp_path):
    first = make_pdf(tmp_path / "a.pdf", PAGES)
    second = tmp_path / "b.pdf"
    second.write_bytes(first.read_bytes())
    assert parse_pdf(first).document_id == parse_pdf(second).document_id


def test_corrupt_file_raises_invalid_pdf(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"this is not a pdf")
    with pytest.raises(InvalidPdfError):
        parse_pdf(path)


def test_missing_file_raises_invalid_pdf(tmp_path):
    with pytest.raises(InvalidPdfError):
        parse_pdf(tmp_path / "nope.pdf")


def test_encrypted_pdf_raises_invalid_pdf(make_pdf, tmp_path):
    path = make_pdf(tmp_path / "locked.pdf", PAGES, password="secret")
    with pytest.raises(InvalidPdfError, match="password"):
        parse_pdf(path)


def test_pdf_without_text_layer_raises_scanned(make_pdf, tmp_path):
    path = make_pdf(tmp_path / "scan.pdf", [[], []])
    with pytest.raises(ScannedPdfError):
        parse_pdf(path)
