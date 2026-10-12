from auditor.ingestion.parser import Line, parse_text
from auditor.ingestion.structure import detect_sections


def _sections(text):
    return detect_sections(parse_text(text, "t.txt").lines)


def test_numbered_hierarchy_builds_paths(sample_contract):
    sections = _sections(sample_contract)
    assert [s.path for s in sections] == [
        "Preamble",
        "1", "1 > 1.1", "1 > 1.2",
        "2", "2 > 2.1", "2 > 2.2",
        "3", "3 > 3.1", "3 > 3.2",
        "4", "4 > 4.1",
    ]
    liability = sections[7]
    assert liability.number == "3"
    assert liability.title == "Limitation of Liability"
    assert liability.level == 1
    assert sections[8].level == 2


def test_sections_are_contiguous_and_cover_all_lines(sample_contract):
    lines = parse_text(sample_contract, "t.txt").lines
    sections = detect_sections(lines)
    assert sections[0].line_start == 0
    assert sections[-1].line_end == len(lines)
    for prev, cur in zip(sections, sections[1:]):
        assert prev.line_end == cur.line_start


def test_no_headings_gives_single_section():
    sections = _sections("just some text\nwithout any structure")
    assert len(sections) == 1
    assert (sections[0].title, sections[0].path) == ("Document", "Document")
    assert (sections[0].line_start, sections[0].line_end) == (0, 2)


def test_first_heading_at_top_has_no_preamble():
    sections = _sections("\n1. Scope\nText here")
    assert [s.path for s in sections] == ["1"]
    assert sections[0].line_start == 0


def test_lines_starting_with_numbers_are_not_headings():
    text = "1. Payment\nPayment is due within\n30 days after the invoice date and\n2 copies of each invoice are required."
    assert [s.path for s in _sections(text)] == ["1"]


def test_lowercase_after_number_is_not_a_heading():
    assert [s.path for s in _sections("1. Scope\n2. the parties agree")] == ["1"]


def test_cross_reference_at_line_start_is_not_a_heading():
    text = "1. Scope\nSection 5.2 of this Agreement applies.\nSection 7 of this Agreement also applies."
    assert [s.path for s in _sections(text)] == ["1"]


def test_article_headings_push_numbered_clauses_down():
    text = "ARTICLE IV - PAYMENT\n4.1 Fees are due monthly.\nARTICLE V\n5.1 Term is one year."
    sections = _sections(text)
    assert [s.path for s in sections] == ["IV", "IV > 4.1", "V", "V > 5.1"]
    assert sections[0].title == "PAYMENT"
    assert sections[2].title == "ARTICLE V"


def test_turkish_madde_heading():
    sections = _sections("Madde 5 - Fesih\nTaraflar otuz gün önceden bildirerek feshedebilir.")
    assert sections[0].number == "5"
    assert sections[0].title == "Fesih"


def test_title_is_cut_at_first_sentence_and_80_chars():
    sections = _sections("1. Fees. The Customer shall pay.\n2. " + "A" * 200)
    assert sections[0].title == "Fees"
    assert len(sections[1].title) == 80


def test_large_font_line_is_a_heading():
    def line(text, size, pos):
        return Line(text, 1, (0.0, 0.0, 1.0, 1.0), size, pos, pos + len(text))

    lines = [
        line("Confidentiality", 16.0, 0),
        line("Each party keeps the other party's information secret.", 11.0, 16),
        line("The obligation survives termination of the agreement.", 11.0, 71),
    ]
    sections = detect_sections(lines)
    assert [s.path for s in sections] == ["Confidentiality"]
    assert sections[0].number is None
