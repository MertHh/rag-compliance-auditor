import threading
import time

from fakes import FakeLLM, audit_llm, fake_services
from fastapi.testclient import TestClient

from auditor.api.main import create_app
from auditor.audit.prompts import Evaluation


def _ingest(services, contract_pdf) -> str:
    return services.indexer.ingest_pdf(contract_pdf).document_id


def wait_for(client, audit_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/audits/{audit_id}")
        if response.status_code != 202:
            return response
        time.sleep(0.05)
    raise AssertionError(f"audit {audit_id} still running after {timeout}s")


def test_audit_runs_in_background_then_comes_from_cache(api, api_services, contract_pdf):
    document_id = _ingest(api_services, contract_pdf)
    started = api.post("/audits", json={"document_id": document_id, "playbook": "test_pb"})
    assert started.status_code == 202
    job = started.json()
    assert job["status"] == "running" and job["playbook"] == "test_pb"
    assert set(job) == {"audit_id", "document_id", "playbook", "provider", "status",
                        "started_at", "error"}

    report = wait_for(api, job["audit_id"])
    assert report.status_code == 200
    body = report.json()
    assert body["audit_id"] == job["audit_id"] and body["risk_score"] == 40.0

    cached = api.post("/audits", json={"document_id": document_id, "playbook": "test_pb"})
    assert cached.status_code == 200
    assert cached.json()["cached"] is True and cached.json()["audit_id"] == job["audit_id"]

    forced = api.post("/audits", json={"document_id": document_id, "playbook": "test_pb",
                                       "force": True})
    assert forced.status_code == 202 and forced.json()["audit_id"] != job["audit_id"]
    wait_for(api, forced.json()["audit_id"])

    listed = api.get("/audits", params={"document_id": document_id}).json()
    assert [a["audit_id"] for a in listed] == [forced.json()["audit_id"], job["audit_id"]]
    assert listed[0]["risk_score"] == 40.0


def test_start_errors_are_raised_before_any_job(api, api_services, api_llm, contract_pdf):
    document_id = _ingest(api_services, contract_pdf)
    api_llm.calls.clear()
    missing = api.post("/audits", json={"document_id": "0" * 64, "playbook": "test_pb"})
    assert (missing.status_code, missing.json()) == (404, {"detail": f"document {'0' * 64} not found"})
    unsafe = api.post("/audits", json={"document_id": "..\\..\\x", "playbook": "test_pb"})
    assert unsafe.status_code == 404
    no_playbook = api.post("/audits", json={"document_id": document_id, "playbook": "nope"})
    assert no_playbook.status_code == 404
    assert "available: test_pb" in no_playbook.json()["detail"]
    assert api.get("/audits").json() == []
    assert api_llm.calls == []


def test_unavailable_provider_is_503(tmp_path, playbooks_dir, contract_pdf):
    services = fake_services(tmp_path, playbooks_dir, FakeLLM(unavailable="Ollama is not reachable"))
    document_id = _ingest(services, contract_pdf)
    with TestClient(create_app(services)) as client:
        response = client.post("/audits", json={"document_id": document_id, "playbook": "test_pb",
                                                "provider": "ollama"})
    assert (response.status_code, response.json()) == (503, {"detail": "Ollama is not reachable"})


def test_same_audit_started_twice_while_running_is_one_job(tmp_path, playbooks_dir, contract_pdf):
    release = threading.Event()
    missing = Evaluation(clause_found=False, matches_criteria=False, reasoning="none", quotes=[])

    def slow_evaluation(user):
        release.wait(10)
        return missing

    services = fake_services(tmp_path, playbooks_dir, audit_llm(Evaluation=slow_evaluation))
    document_id = _ingest(services, contract_pdf)
    with TestClient(create_app(services)) as client:
        body = {"document_id": document_id, "playbook": "test_pb"}
        first = client.post("/audits", json=body).json()
        second = client.post("/audits", json=body).json()
        assert second["audit_id"] == first["audit_id"]
        assert client.get(f"/audits/{first['audit_id']}/trace").status_code == 409
        release.set()
        assert wait_for(client, first["audit_id"]).status_code == 200
    assert len(services.audits.list_audits()) == 1


def test_crashed_job_reports_500(api, api_services, contract_pdf, monkeypatch):
    document_id = _ingest(api_services, contract_pdf)

    def crash(prepared, audit_id=None):
        raise RuntimeError("disk full")

    monkeypatch.setattr(api_services.auditor, "execute", crash)
    job = api.post("/audits", json={"document_id": document_id, "playbook": "test_pb"}).json()
    response = wait_for(api, job["audit_id"])
    assert (response.status_code, response.json()) == (500, {"detail": "audit failed: RuntimeError: disk full"})


def test_trace_review_and_unknown_ids(api, api_services, contract_pdf):
    document_id = _ingest(api_services, contract_pdf)
    audit_id = api.post("/audits", json={"document_id": document_id, "playbook": "test_pb"}).json()["audit_id"]
    wait_for(api, audit_id)

    trace = api.get(f"/audits/{audit_id}/trace").json()
    assert {event["rule_id"] for event in trace} == {"liability_cap", "confidentiality"}
    assert {"node", "started_at", "duration_s", "input_tokens", "cost_usd"} <= set(trace[0])

    review = api.post(f"/audits/{audit_id}/findings/liability_cap/review",
                      json={"decision": "accepted", "note": "checked clause 2"})
    assert review.status_code == 200
    assert review.json()["decision"] == "accepted"
    finding = next(f for f in api.get(f"/audits/{audit_id}").json()["findings"]
                   if f["rule_id"] == "liability_cap")
    assert finding["review"]["note"] == "checked clause 2"

    bad = api.post(f"/audits/{audit_id}/findings/liability_cap/review", json={"decision": "maybe"})
    assert bad.status_code == 422
    assert api.post(f"/audits/{audit_id}/findings/nope/review",
                    json={"decision": "rejected"}).status_code == 404
    unknown = "f" * 32
    assert api.get(f"/audits/{unknown}").status_code == 404
    assert api.get(f"/audits/{unknown}/trace").status_code == 404
    assert api.post(f"/audits/{unknown}/findings/liability_cap/review",
                    json={"decision": "accepted"}).status_code == 404
