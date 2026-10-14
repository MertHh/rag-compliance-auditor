import io
from html import escape
from pathlib import Path

import pymupdf

STATUS_TEXT = {
    "uyumlu": "Compliant",
    "uyumsuz": "Non-compliant",
    "eksik": "Missing",
    "belirsiz": "Uncertain",
    "hata": "Error",
}
# Same status colours as the UI; a text label always accompanies them.
STATUS_RGB = {
    "uyumlu": (0.047, 0.639, 0.047),
    "uyumsuz": (0.816, 0.231, 0.231),
    "eksik": (0.925, 0.514, 0.353),
    "belirsiz": (0.980, 0.698, 0.098),
    "hata": (0.537, 0.529, 0.506),
}
_CSS = """
body { font-family: sans-serif; font-size: 10pt; color: #0b0b0b; }
h1 { font-size: 16pt; margin-bottom: 4pt; }
h2 { font-size: 12pt; margin-top: 14pt; margin-bottom: 2pt; }
p { margin-top: 2pt; margin-bottom: 2pt; }
.muted { color: #52514e; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 0.5pt solid #c3c2b7; padding: 3pt; text-align: left; vertical-align: top; }
blockquote { margin-left: 10pt; color: #52514e; }
"""


def _status(value: str) -> str:
    return STATUS_TEXT.get(value, value)


def _finding_html(finding: dict) -> str:
    evidence = finding["evidence"]
    parts = [
        f"<h2>{escape(finding['title'])} ({escape(finding['rule_id'])})</h2>",
        f"<p><b>{escape(_status(finding['status']))}</b> · severity "
        f"{escape(finding['severity'])} · risk {finding['risk']}</p>",
        f"<p class='muted'>Evidence: {evidence['queries_tried']} queries, "
        f"{evidence['sections_examined']} sections examined</p>",
    ]
    if finding.get("reasoning"):
        parts.append(f"<p>{escape(finding['reasoning'])}</p>")
    if finding.get("error"):
        parts.append(f"<p>Error: {escape(finding['error'])}</p>")
    for citation in finding["citations"]:
        page = citation["page"] if citation["page"] is not None else "-"
        parts.append(f"<blockquote>“{escape(citation['quote'])}” "
                     f"(p{page}, {escape(citation['section_path'] or '-')})</blockquote>")
    review = finding.get("review")
    if review:
        parts.append(f"<p>Review: <b>{escape(review['decision'])}</b> {escape(review['note'])}</p>")
    return "\n".join(parts)


def report_html(report: dict) -> str:
    risk = "-" if report["risk_score"] is None else f"{report['risk_score']:.1f}"
    totals = report["totals"]
    rows = "".join(
        f"<tr><td>{escape(f['rule_id'])}</td><td>{escape(_status(f['status']))}</td>"
        f"<td>{escape(f['severity'])}</td><td>{f['risk']}</td></tr>"
        for f in report["findings"]
    )
    findings = "".join(_finding_html(f) for f in report["findings"])
    return (
        "<h1>Compliance audit</h1>"
        f"<p><b>Risk score: {risk}</b> (0 = no risk, 100 = highest)</p>"
        f"<p class='muted'>Playbook {escape(report['playbook'])} · {escape(report['provider'])} "
        f"{escape(report['model'])} · {escape(report['created_at'])} · {totals['duration_s']} s · "
        f"${totals['cost_usd']:.4f}</p>"
        f"<p class='muted'>Audit {escape(report['audit_id'])} · document "
        f"{escape(report['document_id'])}</p>"
        f"<table><tr><th>Rule</th><th>Status</th><th>Severity</th><th>Risk</th></tr>{rows}</table>"
        f"{findings}"
    )


def _render_html(html: str) -> pymupdf.Document:
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    story = pymupdf.Story(html=html, user_css=_CSS)
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (50, 50, -50, -50)
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return pymupdf.open("pdf", buffer.getvalue())


def report_pdf(report: dict, source_pdf: Path | None) -> bytes:
    out = _render_html(report_html(report))
    if source_pdf is not None:
        offset = out.page_count
        with pymupdf.open(source_pdf) as source:
            out.insert_pdf(source)
            source_pages = source.page_count
        for finding in report["findings"]:
            color = STATUS_RGB.get(finding["status"], STATUS_RGB["hata"])
            label = f"{finding['rule_id']}: {_status(finding['status'])}"
            for citation in finding["citations"]:
                for box in citation["bboxes"]:
                    if not 1 <= box["page"] <= source_pages:
                        continue
                    page = out[offset + box["page"] - 1]
                    annot = page.add_highlight_annot(pymupdf.Rect(box["bbox"]))
                    annot.set_colors(stroke=color)
                    annot.set_info(content=label)
                    annot.update()
    data = out.tobytes(garbage=3, deflate=True)
    out.close()
    return data
