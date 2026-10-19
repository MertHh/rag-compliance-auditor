from datetime import date

from viewmodels import (
    NODE_COLORS,
    NODE_ORDER,
    SEARCH_COLOR,
    STATUS_COLORS,
    bbox_annotations,
    build_filters,
    citation_annotations,
    document_label,
    document_rows,
    finding_rows,
    label_column,
    md_escape,
    md_quote,
    numeric_columns,
    rule_totals,
    run_label,
    search_rows,
    status_label,
    trace_rows,
)

DOC = {"document_id": "ab" * 32, "filename": "msa.pdf", "doc_type": None, "date": "2024-03-01",
       "parties": ["Acme Corp", "Beta LLC"], "jurisdiction": "New York", "has_pdf": True,
       "indexed": False}
BOX = {"page": 2, "bbox": [72.0, 100.0, 300.0, 112.5]}


def test_status_labels_always_carry_text():
    assert status_label("uyumlu") == "✅ Compliant"
    assert status_label("eksik") == "🟠 Missing"
    assert status_label("unknown") == "unknown"
    assert set(STATUS_COLORS) == {"uyumlu", "uyumsuz", "eksik", "belirsiz", "hata"}


def test_document_label_and_rows():
    assert document_label(DOC) == "msa.pdf · abababab"
    assert document_label({**DOC, "filename": None}) == "abababababab · abababab"
    [row] = document_rows([DOC])
    assert row == {"File": "msa.pdf", "Type": "", "Date": "2024-03-01",
                   "Parties": "Acme Corp, Beta LLC", "Jurisdiction": "New York",
                   "Indexed": "no — upload again", "Source": "PDF", "ID": "abababababab"}


def test_build_filters_drops_empty_values():
    assert build_filters([], [], [], None, None) == {}
    assert build_filters(["d1"], ["MSA"], [], date(2024, 1, 1), None) == {
        "document_ids": ["d1"], "doc_types": ["MSA"], "date_from": "2024-01-01"}


def test_search_rows():
    result = {"chunks": [{
        "section_path": "3 > 3.1", "pages": [2, 3], "bboxes": [BOX],
        "text": "The total   liability\nshall not exceed " + "x" * 200,
        "scores": {"bm25_rank": 2, "bm25_score": 1.2, "dense_rank": None, "dense_score": None,
                   "rrf_score": 0.0161, "fused_rank": 3, "rerank_score": 0.91234,
                   "final_rank": 1, "rank_change": 2},
    }]}
    [row] = search_rows(result)
    assert row["Rank"] == 1 and row["Change"] == "+2"
    assert (row["BM25"], row["Dense"], row["RRF"], row["Rerank"]) == ("#2", "-", "0.0161", "0.912")
    assert row["Pages"] == "2, 3" and row["Section"] == "3 > 3.1"
    assert row["Text"].startswith("The total liability shall not exceed")
    assert row["Text"].endswith("…") and len(row["Text"]) == 161


def test_bbox_annotations_convert_corners_to_size():
    assert bbox_annotations([BOX], SEARCH_COLOR) == [
        {"page": 2, "x": 72.0, "y": 100.0, "width": 228.0, "height": 12.5, "color": "#2a78d6"}]


def _finding(status, citations=(), review=None):
    return {"rule_id": f"r_{status}", "title": f"Rule {status}", "status": status,
            "severity": "high", "risk": 3.0, "citations": list(citations),
            "evidence": {"queries_tried": 2, "sections_examined": 4}, "review": review}


def test_findings_and_citation_colours():
    cited = _finding("uyumsuz", [{"bboxes": [BOX]}], {"decision": "accepted", "note": ""})
    report = {"findings": [cited, _finding("eksik")]}
    rows = finding_rows(report)
    assert rows[0] == {"Status": "⛔ Non-compliant", "Rule": "Rule uyumsuz", "Severity": "high",
                       "Risk": 3.0, "Citations": 1, "Evidence": "2 queries · 4 sections",
                       "Review": "accepted"}
    assert rows[1]["Review"] == ""
    [annotation] = citation_annotations(report["findings"])
    assert annotation["color"] == STATUS_COLORS["uyumsuz"]


def test_run_label():
    report = {"created_at": "2026-10-14T09:30:12+00:00", "provider": "openai",
              "model": "gpt-5.5+gpt-5.4-mini",
              "totals": {"duration_s": 38.2, "cost_usd": 0.05512}}
    assert run_label(report) == "2026-10-14 09:30 UTC · openai gpt-5.5+gpt-5.4-mini · 38.2 s · $0.0551"


def _event(rule, node, started, duration, tokens=(100, 20), cost=0.01):
    return {"rule_id": rule, "node": node, "started_at": started, "duration_s": duration,
            "input": "in", "output": "out", "models": ["m"], "input_tokens": tokens[0],
            "output_tokens": tokens[1], "cost_usd": cost}


def test_trace_rows_are_offsets_from_the_first_event():
    events = [
        _event("b", "search", "2026-10-14T10:00:01.500+00:00", 0.5),
        _event("a", "search", "2026-10-14T10:00:00.000+00:00", 1.0),
        _event("a", "evaluate", "2026-10-14T10:00:01.000+00:00", 2.0),
    ]
    rows = trace_rows(events)
    assert [(r["rule_id"], r["node"], r["start_s"], r["end_s"]) for r in rows] == [
        ("a", "search", 0.0, 1.0), ("a", "evaluate", 1.0, 3.0), ("b", "search", 1.5, 2.0)]
    assert rows[0]["tokens"] == 120
    assert rule_totals(rows) == [
        {"Rule": "a", "Steps": 2, "Seconds": 3.0, "Tokens": 240, "Cost ($)": 0.02},
        {"Rule": "b", "Steps": 1, "Seconds": 0.5, "Tokens": 120, "Cost ($)": 0.01},
    ]
    assert trace_rows([]) == []


def test_node_colours_are_fixed_per_step():
    assert NODE_ORDER == ["search", "rewrite", "evaluate", "verify", "wide_scan"]
    assert len(NODE_COLORS) == len(NODE_ORDER) == len(set(NODE_COLORS))


def test_benchmark_columns():
    rows = [{"config": "bm25", "recall@5": 0.61, "mrr": None, "ok": True},
            {"config": "hybrid", "recall@5": 0.78, "mrr": 0.66, "ok": False}]
    assert numeric_columns(rows) == ["recall@5", "mrr"]
    assert label_column(rows) == "config"
    assert numeric_columns([]) == [] and label_column([]) is None


def test_md_escape_keeps_dollar_amounts_literal():
    assert md_escape("$500,000 or $1,000,000 *x*") == r"\$500,000 or \$1,000,000 \*x\*"
    assert md_escape(r"a_b [c](d) `e` <f> #g \ ") == r"a\_b \[c\](d) \`e\` \<f\> \#g \\ "
    assert md_escape("- item\n  + sub\n1. one") == "\\- item\n  \\+ sub\n1\\. one"
    assert md_escape("") == ""


def test_md_quote_keeps_a_quote_broken_by_pdf_lines_in_one_blockquote():
    assert md_quote("unless required to\ndo so by $5 law") == r"> unless required to do so by \$5 law"
    assert md_quote("  1. first\n\n second ") == r"> 1\. first second"
    assert md_quote("Regu-\nlation (EU) and third-\nParty") == "> Regulation (EU) and third- Party"
