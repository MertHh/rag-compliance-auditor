from types import SimpleNamespace

import pytest
from fakes import (
    CONTRACT_PAGES,
    FakeEmbedder,
    FakeLLM,
    FakeReranker,
    FakeSparseEncoder,
    audit_llm,
    by_rule,
)

from auditor.audit.nodes import AuditConfig
from auditor.audit.playbook import PlaybookNotFound
from auditor.audit.prompts import Evaluation
from auditor.audit.runner import Auditor, cache_key
from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.indexer import Indexer
from auditor.lazy import Lazy
from auditor.llm.base import ProviderUnavailableError
from auditor.retrieval.pipeline import Retriever
from auditor.storage.db import AuditStore
from auditor.storage.docstore import DocumentNotFound, DocumentStore


@pytest.fixture
def env(tmp_path, make_pdf, playbooks_dir):
    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse = FakeEmbedder(), FakeSparseEncoder()
    pdf = make_pdf(tmp_path / "contract.pdf", CONTRACT_PAGES)
    doc_id = Indexer(store, embedder, sparse, docstore).ingest_pdf(pdf).document_id
    return SimpleNamespace(
        store=store,
        retriever=Retriever(store, embedder, sparse, FakeReranker(), docstore),
        docstore=docstore,
        audits=AuditStore(tmp_path / "auditor.db"),
        playbooks=playbooks_dir,
        doc_id=doc_id,
    )


def _auditor(env, llm):
    return Auditor(env.retriever, env.docstore, env.audits, env.playbooks, lambda name: llm,
                   AuditConfig(concurrency=2))


def test_full_audit_report(env):
    report = _auditor(env, audit_llm()).run(env.doc_id, "test_pb", "openai")
    assert report["document_id"] == env.doc_id
    assert (report["playbook"], report["provider"], report["model"]) == ("test_pb", "fake", "fake-eval+fake-small")
    assert report["cached"] is False
    assert report["risk_score"] == 40.0
    assert report["errors"] == []
    findings = {f["rule_id"]: f for f in report["findings"]}

    liability = findings["liability_cap"]
    assert (liability["status"], liability["risk"], liability["severity"]) == ("uyumlu", 0.0, "high")
    [citation] = liability["citations"]
    assert citation["page"] == 2
    assert citation["bboxes"][0]["page"] == 2
    assert citation["quote"].startswith("The total liability")
    assert liability["evidence"]["queries_tried"] == 1
    assert liability["review"] is None

    confidentiality = findings["confidentiality"]
    assert (confidentiality["status"], confidentiality["risk"]) == ("eksik", 2.0)
    assert confidentiality["citations"] == []
    assert confidentiality["evidence"]["queries_tried"] == 2
    assert confidentiality["evidence"]["sections_examined"] >= 1

    totals = report["totals"]
    assert totals["input_tokens"] > 0 and totals["cost_usd"] > 0 and totals["duration_s"] >= 0


def test_report_and_trace_are_stored(env):
    report = _auditor(env, audit_llm()).run(env.doc_id, "test_pb", "openai")
    assert env.audits.get_report(report["audit_id"])["risk_score"] == 40.0
    trace = env.audits.get_trace(report["audit_id"])
    assert {event["rule_id"] for event in trace} == {"liability_cap", "confidentiality"}
    assert any(e["node"] == "wide_scan" and e["rule_id"] == "confidentiality" for e in trace)


def test_second_run_is_served_from_cache_with_reviews(env):
    llm = audit_llm()
    auditor = _auditor(env, llm)
    first = auditor.run(env.doc_id, "test_pb", "openai")
    calls = len(llm.calls)
    env.audits.set_review(first["audit_id"], "confidentiality", "accepted", "checked")

    second = auditor.run(env.doc_id, "test_pb", "openai")
    assert second["cached"] is True
    assert second["audit_id"] == first["audit_id"]
    assert len(llm.calls) == calls
    review = {f["rule_id"]: f["review"] for f in second["findings"]}["confidentiality"]
    assert review["decision"] == "accepted"

    forced = auditor.run(env.doc_id, "test_pb", "openai", force=True)
    assert forced["cached"] is False
    assert forced["audit_id"] != first["audit_id"]
    assert len(llm.calls) > calls
    assert len(env.audits.list_audits(env.doc_id)) == 2


def test_unexpected_rule_failure_is_isolated_and_not_cached(env):
    llm = audit_llm(Evaluation=by_rule({
        "Liability cap": Evaluation(clause_found=True, matches_criteria=True, reasoning="ok",
                                    quotes=["The total liability shall not exceed the fees paid in twelve months."]),
        "Confidentiality": RuntimeError("disk on fire"),
    }))
    auditor = _auditor(env, llm)
    report = auditor.run(env.doc_id, "test_pb", "openai")
    findings = {f["rule_id"]: f for f in report["findings"]}
    assert findings["confidentiality"]["status"] == "hata"
    assert findings["confidentiality"]["risk"] is None
    assert "disk on fire" in findings["confidentiality"]["error"]
    assert findings["liability_cap"]["status"] == "uyumlu"
    assert report["errors"] == [{"rule_id": "confidentiality",
                                 "message": findings["confidentiality"]["error"]}]
    assert report["risk_score"] == 0.0

    again = auditor.run(env.doc_id, "test_pb", "openai")
    assert again["cached"] is False
    assert again["audit_id"] != report["audit_id"]


def test_llm_error_marks_rule_as_error(env):
    from auditor.llm.base import LLMError
    llm = audit_llm(Evaluation=LLMError("schema mismatch"))
    report = _auditor(env, llm).run(env.doc_id, "test_pb", "openai")
    assert {f["status"] for f in report["findings"]} == {"hata"}
    assert report["risk_score"] is None
    assert len(report["errors"]) == 2


def test_bad_requests_fail_before_any_llm_call(env):
    llm = audit_llm()
    auditor = _auditor(env, llm)
    with pytest.raises(DocumentNotFound):
        auditor.run("0" * 64, "test_pb", "openai")
    with pytest.raises(PlaybookNotFound, match="available: test_pb"):
        auditor.run(env.doc_id, "nope", "openai")
    down = FakeLLM(unavailable="Ollama is not reachable at http://localhost:11434")
    with pytest.raises(ProviderUnavailableError, match="not reachable"):
        _auditor(env, down).run(env.doc_id, "test_pb", "ollama")
    assert llm.calls == [] and down.calls == []
    assert env.audits.list_audits() == []


def test_cache_key_changes_with_each_part():
    base = cache_key("doc", "pb", "openai", "m1")
    assert len(base) == 64
    assert base == cache_key("doc", "pb", "openai", "m1")
    others = {
        cache_key("doc2", "pb", "openai", "m1"),
        cache_key("doc", "pb2", "openai", "m1"),
        cache_key("doc", "pb", "ollama", "m1"),
        cache_key("doc", "pb", "openai", "m2"),
        cache_key("doc", "pb", "openai", "m1", prompt_version="999"),
    }
    assert base not in others and len(others) == 5


def test_prepare_then_execute_with_given_id(env):
    auditor = _auditor(env, audit_llm())
    prepared = auditor.prepare(env.doc_id, "test_pb", "openai")
    assert prepared.document_id == env.doc_id and prepared.playbook.key == "test_pb"
    assert auditor.cached(prepared) is None

    report = auditor.execute(prepared, "a" * 32)
    assert report["audit_id"] == "a" * 32
    assert env.audits.get_report("a" * 32)["risk_score"] == 40.0
    assert auditor.cached(prepared)["cached"] is True


def test_cached_audit_does_not_load_models(env):
    _auditor(env, audit_llm()).run(env.doc_id, "test_pb", "openai")
    loaded = []

    def never(name):
        def factory():
            loaded.append(name)
            raise AssertionError(f"{name} was loaded")
        return Lazy(factory)

    retriever = Retriever(env.store, never("embedder"), never("sparse"), never("reranker"),
                          env.docstore)
    auditor = Auditor(retriever, env.docstore, env.audits, env.playbooks, lambda name: audit_llm())
    report = auditor.run(env.doc_id, "test_pb", "openai")
    assert report["cached"] is True
    assert loaded == []
