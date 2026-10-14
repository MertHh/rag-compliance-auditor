import json

import pytest
from fakes import CONTRACT_PAGES, FakeLLM, audit_llm, fake_services

from auditor.cli import main

PAGES = CONTRACT_PAGES


@pytest.fixture
def llm():
    return audit_llm()


@pytest.fixture
def services(tmp_path, playbooks_dir, llm):
    return fake_services(tmp_path, playbooks_dir, llm)


def _ingest(services, make_pdf, tmp_path, capsys) -> str:
    assert main(["ingest", str(make_pdf(tmp_path / "c.pdf", PAGES))], services) == 0
    out = capsys.readouterr().out
    return out.strip().rsplit(" ", 1)[-1]


def test_ingest_then_search(services, make_pdf, tmp_path, capsys):
    path = make_pdf(tmp_path / "c.pdf", PAGES)
    assert main(["ingest", str(path)], services) == 0
    out = capsys.readouterr().out
    assert "indexed 2 chunks" in out

    assert main(["ingest", str(path)], services) == 0
    assert "already indexed" in capsys.readouterr().out

    assert main(["search", "total liability fees", "--top", "1"], services) == 0
    out = capsys.readouterr().out
    assert "1. [2]" in out
    assert "p[2]" in out
    assert "rerank=" in out
    assert "The total liability shall not exceed" in out


def test_search_modes_and_no_rerank(services, make_pdf, tmp_path, capsys):
    main(["ingest", str(make_pdf(tmp_path / "c.pdf", PAGES))], services)
    capsys.readouterr()
    assert main(["search", "liability", "--mode", "bm25", "--no-rerank"], services) == 0
    out = capsys.readouterr().out
    assert "bm25=#1" in out
    assert "dense=-" in out
    assert "rerank=-" in out


def test_search_with_no_results_says_so(services, capsys):
    assert main(["search", "liability"], services) == 0
    assert "no sufficient evidence" in capsys.readouterr().out


def test_ingest_errors_exit_with_1_and_message(services, tmp_path, capsys):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    assert main(["ingest", str(broken)], services) == 1
    assert "error:" in capsys.readouterr().err
    assert main(["ingest", str(tmp_path / "missing.pdf")], services) == 1
    assert "error:" in capsys.readouterr().err


def test_ingest_extracts_metadata(services, make_pdf, tmp_path, capsys):
    doc_id = _ingest(services, make_pdf, tmp_path, capsys)
    assert services.docstore.metadata(doc_id)["doc_type"] == "Services Agreement"


def test_ingest_without_provider_still_indexes(tmp_path, playbooks_dir, make_pdf, capsys):
    down = fake_services(tmp_path, playbooks_dir, FakeLLM(unavailable="OPENAI_API_KEY is not set"))
    assert main(["ingest", str(make_pdf(tmp_path / "c.pdf", PAGES))], down) == 0
    captured = capsys.readouterr()
    assert "metadata extraction skipped: OPENAI_API_KEY is not set" in captured.err
    assert "indexed 2 chunks" in captured.out


def test_ingest_no_metadata_skips_llm(services, llm, make_pdf, tmp_path):
    assert main(["ingest", str(make_pdf(tmp_path / "c.pdf", PAGES)), "--no-metadata"], services) == 0
    assert llm.calls == []


def test_ask_prints_answer_and_citation(services, make_pdf, tmp_path, capsys):
    doc_id = _ingest(services, make_pdf, tmp_path, capsys)
    assert main(["ask", "total liability fees paid", "--document", doc_id], services) == 0
    out = capsys.readouterr().out
    assert "Liability is capped at the fees paid in twelve months." in out
    assert '"The total liability shall not exceed' in out
    assert "(p2, " in out


def test_ask_without_evidence(services, make_pdf, tmp_path, capsys):
    _ingest(services, make_pdf, tmp_path, capsys)
    assert main(["ask", "zebra quantum"], services) == 0
    assert "I could not find a statement" in capsys.readouterr().out


def test_audit_prints_findings_then_uses_cache(services, make_pdf, tmp_path, capsys):
    doc_id = _ingest(services, make_pdf, tmp_path, capsys)
    assert main(["audit", doc_id, "test_pb"], services) == 0
    out = capsys.readouterr().out
    assert "risk 40.0" in out
    assert "uyumlu    high   liability_cap" in out
    assert "eksik     medium confidentiality" in out
    assert "(cached)" not in out

    assert main(["audit", doc_id, "test_pb"], services) == 0
    assert "(cached)" in capsys.readouterr().out


def test_audit_json_output(services, make_pdf, tmp_path, capsys):
    doc_id = _ingest(services, make_pdf, tmp_path, capsys)
    assert main(["audit", doc_id, "test_pb", "--json"], services) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["risk_score"] == 40.0


def test_audit_errors_exit_with_1(services, make_pdf, tmp_path, capsys):
    doc_id = _ingest(services, make_pdf, tmp_path, capsys)
    assert main(["audit", "0" * 64, "test_pb"], services) == 1
    assert "is not indexed" in capsys.readouterr().err
    assert main(["audit", doc_id, "missing"], services) == 1
    assert "available: test_pb" in capsys.readouterr().err
