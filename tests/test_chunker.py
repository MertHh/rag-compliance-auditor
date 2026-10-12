from auditor.ingestion.chunker import build_chunks, locate
from auditor.ingestion.parser import parse_pdf, parse_text
from auditor.ingestion.structure import detect_sections
from auditor.tokens import count_tokens


def _chunks(text, **kwargs):
    doc = parse_text(text, "t.txt")
    return doc, build_chunks(doc, detect_sections(doc.lines), **kwargs)


def test_child_carries_section_metadata_and_parent(sample_contract):
    doc, chunks = _chunks(sample_contract)
    chunk = next(c for c in chunks if c.section_path == "3 > 3.1")
    assert chunk.text.startswith("3.1 The total aggregate liability")
    assert doc.text[chunk.char_start:chunk.char_end] == chunk.text
    parent = doc.text[chunk.parent_start:chunk.parent_end]
    assert parent.startswith("3. Limitation of Liability")
    assert "3.2 Neither party" in parent
    assert "4. Governing Law" not in parent
    assert chunk.parent_section_path == "3"
    assert chunk.parent_id == f"{doc.document_id}:{chunk.parent_start}-{chunk.parent_end}"
    assert chunk.document_id == doc.document_id
    assert chunk.context_prefix == ""


def test_chunks_in_one_small_section_share_a_parent(sample_contract):
    _, chunks = _chunks(sample_contract)
    parents = {c.parent_id for c in chunks if c.section_path.split(" > ")[0] == "3"}
    assert len(parents) == 1


def test_chunk_ids_are_unique_and_stable(sample_contract):
    _, first = _chunks(sample_contract)
    _, second = _chunks(sample_contract)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert len({c.chunk_id for c in first}) == len(first)


def test_parent_falls_back_to_subsection_when_top_section_is_too_large():
    body = " ".join(["word"] * 30) + "."
    doc, chunks = _chunks(f"1. Big\n1.1 Alpha {body}\n1.2 Beta {body}", max_parent_tokens=40)
    chunk = next(c for c in chunks if c.section_path == "1 > 1.1")
    assert chunk.parent_section_path == "1 > 1.1"
    assert count_tokens(doc.text[chunk.parent_start:chunk.parent_end]) <= 40


def test_parent_is_the_child_itself_when_nothing_fits():
    doc, chunks = _chunks(" ".join(["tok"] * 300), max_child_tokens=100, max_parent_tokens=50)
    for chunk in chunks:
        assert (chunk.parent_start, chunk.parent_end) == (chunk.char_start, chunk.char_end)


def test_long_section_is_split_at_sentences_within_limit():
    sentences = " ".join(f"Sentence number {i} has several words in it." for i in range(60))
    _, chunks = _chunks("1. Long\n" + sentences, max_child_tokens=50)
    assert len(chunks) > 1
    assert all(count_tokens(c.text) <= 50 for c in chunks)
    assert all(c.text.endswith(".") or c.text.endswith("Long") for c in chunks)


def test_text_without_punctuation_is_hard_split():
    _, chunks = _chunks(" ".join(["tok"] * 500), max_child_tokens=100)
    assert len(chunks) == 5
    assert all(count_tokens(c.text) == 100 for c in chunks)


def test_every_non_whitespace_char_is_in_exactly_one_chunk(sample_contract):
    noisy = (
        sample_contract
        + "\n\nThe supplier shall deliver:\n1. apples\n2. Oranges and pears\n"
        + "30 days after delivery\nPage 3 of 12\n4.2 Late Delivery. Penalties apply.\n"
    )
    doc, chunks = _chunks(noisy, max_child_tokens=30)
    covered = [0] * len(doc.text)
    for chunk in chunks:
        for i in range(chunk.char_start, chunk.char_end):
            covered[i] += 1
    assert max(covered) == 1
    for i, ch in enumerate(doc.text):
        if not ch.isspace():
            assert covered[i] == 1, f"char {i!r} {ch!r} not covered"


def test_empty_document_gives_no_chunks():
    _, chunks = _chunks("   \n\n  ")
    assert chunks == []


def test_pdf_chunks_have_pages_and_bboxes(make_pdf, tmp_path):
    path = make_pdf(tmp_path / "c.pdf", [
        [("1. Definitions", 11),
         ("Services means the consulting services described in Exhibit A.", 11)],
        [("2. Liability", 11),
         ("The total liability shall not exceed the fees paid in twelve months.", 11)],
    ])
    doc = parse_pdf(path)
    chunks = build_chunks(doc, detect_sections(doc.lines))
    by_path = {c.section_path: c for c in chunks}
    assert by_path["1"].pages == [1]
    assert by_path["2"].pages == [2]
    assert len(by_path["2"].bboxes) == 2
    assert all(len(box.bbox) == 4 and box.page == 2 for box in by_path["2"].bboxes)


def test_locate_returns_only_lines_overlapping_the_span(make_pdf, tmp_path):
    path = make_pdf(tmp_path / "c.pdf", [
        [("1. Definitions and the interpretation of all terms", 11),
         ("Services means the consulting services in Exhibit A.", 11)],
    ])
    doc = parse_pdf(path)
    start = doc.text.index("consulting")
    boxes = locate(doc, start, start + len("consulting"))
    assert len(boxes) == 1
    assert boxes[0].page == 1
    assert locate(parse_text("plain", "t.txt"), 0, 5) == []
