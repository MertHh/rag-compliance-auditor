"""Turns API responses into table rows, labels and PDF annotations. No Streamlit here,
so everything is tested directly."""

import re
from datetime import date, datetime

STATUS_TEXT = {
    "uyumlu": "Compliant",
    "uyumsuz": "Non-compliant",
    "eksik": "Missing",
    "belirsiz": "Uncertain",
    "hata": "Error",
}
STATUS_ICON = {"uyumlu": "✅", "uyumsuz": "⛔", "eksik": "🟠", "belirsiz": "❔", "hata": "⚠️"}
# Status colours never carry meaning alone: every use sits next to status_label().
STATUS_COLORS = {
    "uyumlu": "#0ca30c",
    "uyumsuz": "#d03b3b",
    "eksik": "#ec835a",
    "belirsiz": "#fab219",
    "hata": "#898781",
}
SEARCH_COLOR = "#2a78d6"
# Agent steps in graph order, coloured with categorical slots 1-5 in fixed order.
NODE_ORDER = ["search", "rewrite", "evaluate", "verify", "wide_scan"]
NODE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]

_SPACES = re.compile(r"\s+")


def status_label(status: str) -> str:
    icon = STATUS_ICON.get(status)
    return f"{icon} {STATUS_TEXT[status]}" if icon else status


def document_label(doc: dict) -> str:
    return f"{doc['filename'] or doc['document_id'][:12]} · {doc['document_id'][:8]}"


def document_rows(docs: list[dict]) -> list[dict]:
    return [
        {
            "File": doc["filename"] or "",
            "Type": doc["doc_type"] or "",
            "Date": doc["date"] or "",
            "Parties": ", ".join(doc["parties"]),
            "Jurisdiction": doc["jurisdiction"] or "",
            "Indexed": "yes" if doc["indexed"] else "no — upload again",
            "Source": "PDF" if doc["has_pdf"] else "text",
            "ID": doc["document_id"][:12],
        }
        for doc in docs
    ]


def build_filters(document_ids, doc_types, jurisdictions, date_from: date | None,
                  date_to: date | None) -> dict:
    filters = {
        "document_ids": list(document_ids),
        "doc_types": list(doc_types),
        "jurisdictions": list(jurisdictions),
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
    }
    return {key: value for key, value in filters.items() if value}


def _preview(text: str, limit: int = 160) -> str:
    flat = _SPACES.sub(" ", text).strip()
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _rank(value: int | None) -> str:
    return "-" if value is None else f"#{value}"


def _score(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def search_rows(result: dict) -> list[dict]:
    rows = []
    for chunk in result["chunks"]:
        scores = chunk["scores"]
        rows.append({
            "Rank": scores["final_rank"],
            "Change": f"{scores['rank_change']:+d}",
            "Section": chunk["section_path"] or "-",
            "Pages": ", ".join(str(page) for page in chunk["pages"]) or "-",
            "BM25": _rank(scores["bm25_rank"]),
            "Dense": _rank(scores["dense_rank"]),
            "RRF": _score(scores["rrf_score"], 4),
            "Rerank": _score(scores["rerank_score"]),
            "Text": _preview(chunk["text"]),
        })
    return rows


def bbox_annotations(bboxes: list[dict], color: str) -> list[dict]:
    """PyMuPDF boxes (x0, y0, x1, y1; points; top-left origin) to streamlit-pdf-viewer
    annotations, which use the same units and origin with a width and height."""
    annotations = []
    for box in bboxes:
        x0, y0, x1, y1 = box["bbox"]
        annotations.append({"page": box["page"], "x": x0, "y": y0, "width": x1 - x0,
                            "height": y1 - y0, "color": color})
    return annotations


def citation_annotations(findings: list[dict]) -> list[dict]:
    annotations = []
    for finding in findings:
        color = STATUS_COLORS.get(finding["status"], STATUS_COLORS["hata"])
        for citation in finding["citations"]:
            annotations.extend(bbox_annotations(citation["bboxes"], color))
    return annotations


def finding_rows(report: dict) -> list[dict]:
    rows = []
    for finding in report["findings"]:
        evidence = finding["evidence"]
        review = finding.get("review")
        rows.append({
            "Status": status_label(finding["status"]),
            "Rule": finding["title"],
            "Severity": finding["severity"],
            "Risk": finding["risk"],
            "Citations": len(finding["citations"]),
            "Evidence": f"{evidence['queries_tried']} queries · {evidence['sections_examined']} sections",
            "Review": review["decision"] if review else "",
        })
    return rows


def run_label(report: dict) -> str:
    totals = report["totals"]
    when = report["created_at"].replace("T", " ")[:16]
    return (f"{when} UTC · {report['provider']} {report['model']} · "
            f"{totals['duration_s']} s · ${totals['cost_usd']:.4f}")


def trace_rows(events: list[dict]) -> list[dict]:
    if not events:
        return []
    starts = [datetime.fromisoformat(event["started_at"]) for event in events]
    origin = min(starts)
    rows = []
    for event, start in zip(events, starts):
        offset = (start - origin).total_seconds()
        rows.append({
            "rule_id": event["rule_id"],
            "node": event["node"],
            "start_s": round(offset, 3),
            "end_s": round(offset + event["duration_s"], 3),
            "duration_s": event["duration_s"],
            "tokens": event["input_tokens"] + event["output_tokens"],
            "cost_usd": event["cost_usd"],
            "models": ", ".join(event["models"]),
            "input": event["input"],
            "output": event["output"],
        })
    return sorted(rows, key=lambda row: (row["rule_id"], row["start_s"]))


def rule_totals(rows: list[dict]) -> list[dict]:
    totals: dict[str, dict] = {}
    for row in rows:
        entry = totals.setdefault(row["rule_id"], {"Rule": row["rule_id"], "Steps": 0,
                                                   "start": row["start_s"], "end": row["end_s"],
                                                   "Tokens": 0, "Cost ($)": 0.0})
        entry["Steps"] += 1
        entry["start"] = min(entry["start"], row["start_s"])
        entry["end"] = max(entry["end"], row["end_s"])
        entry["Tokens"] += row["tokens"]
        entry["Cost ($)"] += row["cost_usd"]
    return [
        {"Rule": e["Rule"], "Steps": e["Steps"], "Seconds": round(e["end"] - e["start"], 3),
         "Tokens": e["Tokens"], "Cost ($)": round(e["Cost ($)"], 4)}
        for e in sorted(totals.values(), key=lambda e: e["Rule"])
    ]


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def numeric_columns(rows: list[dict]) -> list[str]:
    columns = list(dict.fromkeys(key for row in rows for key in row))
    numeric = []
    for column in columns:
        values = [row.get(column) for row in rows if row.get(column) is not None]
        if values and all(_is_number(value) for value in values):
            numeric.append(column)
    return numeric


def label_column(rows: list[dict]) -> str | None:
    numeric = set(numeric_columns(rows))
    columns = list(dict.fromkeys(key for row in rows for key in row))
    return next((column for column in columns if column not in numeric), None)
