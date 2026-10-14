from auditor.audit.citations import verify_quotes
from auditor.ingestion.parser import parse_pdf, parse_text
from auditor.retrieval.pipeline import ParentPassage


def _passage(doc, start_marker, section_path, parent_id="p1"):
    start = doc.text.index(start_marker)
    return ParentPassage(parent_id, doc.document_id, doc.text[start:], start, len(doc.text), section_path, [])


def test_exact_quote_is_verified_with_offsets(sample_contract):
    doc = parse_text(sample_contract, "msa.txt")
    quote = "Either party may terminate this Agreement upon thirty (30) days written notice."
    [citation] = verify_quotes(doc, [quote], [])
    assert doc.text[citation.char_start:citation.char_end] == citation.quote
    assert citation.quote == "Either party may terminate this Agreement upon thirty (30) days written notice"
    assert citation.document_id == doc.document_id
    assert citation.page is None and citation.bboxes == []


def test_whitespace_line_breaks_and_curly_quotes_are_normalized(sample_contract):
    doc = parse_text("The total liability\nshall not  exceed the fees.\n" + sample_contract, "x.txt")
    [first, second] = verify_quotes(
        doc,
        ["The total liability shall not exceed",
         "1.1 “Services” means the consulting   services"],
        [],
    )
    assert first.quote == "The total liability\nshall not  exceed"
    assert second.quote == '1.1 "Services" means the consulting services'


def test_wrapping_quotes_and_ellipsis_are_ignored(sample_contract):
    doc = parse_text(sample_contract, "msa.txt")
    [citation] = verify_quotes(doc, ['"…governed by the laws of the State of New York."'], [])
    assert citation.quote == "governed by the laws of the State of New York"


def test_fabricated_quote_is_dropped(sample_contract):
    doc = parse_text(sample_contract, "msa.txt")
    assert verify_quotes(doc, ["Liability is unlimited for all claims of any kind."], []) == []


def test_short_generic_quote_is_dropped(sample_contract):
    doc = parse_text(sample_contract, "msa.txt")
    assert verify_quotes(doc, ["this Agreement", "the fees paid"], []) == []


def test_quote_from_another_document_is_dropped(sample_contract):
    doc = parse_text(sample_contract, "msa.txt")
    other = parse_text("1. Confidentiality\nEach party shall keep the other party's information confidential.", "nda.txt")
    passages = [_passage(other, "1. Confidentiality", "1")]
    quote = "Each party shall keep the other party's information confidential."
    assert verify_quotes(doc, [quote], passages) == []
    assert len(verify_quotes(other, [quote], passages)) == 1


def test_repeated_text_prefers_the_given_passage():
    text = ("1. Payment\nInvoices are payable within thirty days of receipt.\n"
            "2. Late Payment\nInvoices are payable within thirty days of receipt.")
    doc = parse_text(text, "p.txt")
    passage = _passage(doc, "2. Late Payment", "2")
    [citation] = verify_quotes(doc, ["Invoices are payable within thirty days of receipt."], [passage])
    assert citation.char_start > doc.text.index("2. Late Payment")
    assert citation.section_path == "2"


def test_duplicate_quotes_are_cited_once(sample_contract):
    doc = parse_text(sample_contract, "msa.txt")
    quote = "Neither party shall be liable for indirect or consequential damages."
    assert len(verify_quotes(doc, [quote, quote], [])) == 1


def test_pdf_quote_gets_page_and_line_boxes(make_pdf, tmp_path):
    path = make_pdf(tmp_path / "c.pdf", [
        [("1. Definitions", 11), ("Services means the consulting services.", 11)],
        [("2. Liability", 11), ("The total liability shall not exceed the fees paid.", 11)],
    ])
    doc = parse_pdf(path)
    [citation] = verify_quotes(doc, ["The total liability shall not exceed the fees paid."], [])
    assert citation.page == 2
    assert [box.page for box in citation.bboxes] == [2]
    data = citation.to_dict()
    assert data["page"] == 2
    assert data["bboxes"][0]["page"] == 2
    assert len(data["bboxes"][0]["bbox"]) == 4
