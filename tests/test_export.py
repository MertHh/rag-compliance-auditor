import json

import pymupdf
from fakes import CONTRACT_PAGES, LIABILITY_LINE
from test_api_audits import wait_for

from auditor.audit.export import STATUS_TEXT, report_html, report_pdf


def _report():
    return {
        "audit_id": "a" * 32, "document_id": "d" * 64, "playbook": "test_pb",
        "provider": "openai", "model": "gpt-5.5+gpt-5.4-mini",
        "created_at": "2026-10-14T10:00:00+00:00", "risk_score": 40.0, "cached": False,
        "findings": [
            {"rule_id": "liability_cap", "title": "Liability cap", "type": "must_exist",
             "status": "uyumlu", "severity": "high", "risk": 0.0,
             "reasoning": "Sorumluluk sınırı açıkça yazılmış.",
             "citations": [{"quote": LIABILITY_LINE, "document_id": "d" * 64, "page": 2,
                            "section_path": "2", "char_start": 0, "char_end": 10,
                            "bboxes": [{"page": 2, "bbox": [72.0, 80.0, 400.0, 95.0]}]}],
             "evidence": {"queries_tried": 1, "sections_examined": 2}, "error": None,
             "review": {"decision": "accepted", "note": "ok <b>bold</b>", "updated_at": "x"}},
            {"rule_id": "confidentiality", "title": "Confidentiality", "type": "must_exist",
             "status": "eksik", "severity": "medium", "risk": 2.0,
             "reasoning": "No confidentiality clause.", "citations": [],
             "evidence": {"queries_tried": 3, "sections_examined": 5}, "error": None,
             "review": None},
        ],
        "errors": [],
        "totals": {"duration_s": 38.2, "input_tokens": 1000, "output_tokens": 200, "cost_usd": 0.055},
    }


def _annots(doc) -> int:
    return sum(len(list(page.annots())) for page in doc)


def test_html_escapes_and_labels():
    html = report_html(_report())
    assert "ok &lt;b&gt;bold&lt;/b&gt;" in html
    assert STATUS_TEXT["uyumlu"] in html and STATUS_TEXT["eksik"] in html
    assert "3 queries, 5 sections examined" in html


def test_pdf_without_source_is_report_only():
    with pymupdf.open("pdf", report_pdf(_report(), None)) as doc:
        text = "\n".join(page.get_text() for page in doc)
        assert "Risk score: 40.0" in text
        assert "Sorumluluk sınırı" in text
        assert "liability_cap" in text and "Missing" in text
        assert _annots(doc) == 0


def test_pdf_appends_contract_with_highlights(tmp_path, make_pdf):
    source = make_pdf(tmp_path / "contract.pdf", CONTRACT_PAGES)
    with pymupdf.open("pdf", report_pdf(_report(), source)) as doc:
        first_contract_page = doc.page_count - 2
        assert first_contract_page >= 1
        assert LIABILITY_LINE in doc[first_contract_page + 1].get_text()
        page = doc[first_contract_page + 1]  # keep the page alive while using its annots
        [annot] = list(page.annots())
        assert annot.type[1] == "Highlight"
        assert "liability_cap" in annot.info["content"]
        assert list(doc[first_contract_page].annots()) == []


def test_citation_pages_outside_the_source_are_skipped(tmp_path, make_pdf):
    report = _report()
    report["findings"][0]["citations"][0]["bboxes"][0]["page"] = 9
    source = make_pdf(tmp_path / "contract.pdf", CONTRACT_PAGES)
    with pymupdf.open("pdf", report_pdf(report, source)) as doc:
        assert _annots(doc) == 0


def test_export_endpoint(api, api_services, contract_pdf):
    document_id = api_services.indexer.ingest_pdf(contract_pdf).document_id
    audit_id = api.post("/audits", json={"document_id": document_id, "playbook": "test_pb"}).json()["audit_id"]
    wait_for(api, audit_id)

    as_json = api.get(f"/audits/{audit_id}/export")
    assert as_json.headers["content-disposition"] == f'attachment; filename="audit-{audit_id}.json"'
    assert json.loads(as_json.content)["audit_id"] == audit_id

    as_pdf = api.get(f"/audits/{audit_id}/export", params={"format": "pdf"})
    assert as_pdf.headers["content-type"] == "application/pdf"
    with pymupdf.open("pdf", as_pdf.content) as doc:
        assert doc.page_count >= 3
        assert _annots(doc) >= 1

    assert api.get(f"/audits/{audit_id}/export", params={"format": "docx"}).status_code == 422
    assert api.get("/audits/" + "f" * 32 + "/export").status_code == 404
