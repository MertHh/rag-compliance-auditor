import time

import httpx
import pytest
from apiclient import ApiClient, ApiError


def _wait(client, audit_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state, body = client.audit(audit_id)
        if state == "done":
            return body
        time.sleep(0.05)
    raise AssertionError("audit did not finish")


def test_full_flow_through_the_client(api, contract_pdf):
    client = ApiClient(api)
    pdf = contract_pdf.read_bytes()
    uploaded = client.upload("contract.pdf", pdf, {"doc_type": None, "jurisdiction": "Delaware",
                                                   "parties": ["Acme Corp", "Beta LLC"]})
    document_id = uploaded["document_id"]
    assert uploaded["document"]["jurisdiction"] == "Delaware"
    assert uploaded["document"]["parties"] == ["Acme Corp", "Beta LLC"]
    assert [d["document_id"] for d in client.documents()] == [document_id]
    assert client.document_file(document_id) == pdf

    result = client.search("total liability fees", final_k=1, filters={"document_ids": [document_id]})
    assert result["chunks"][0]["pages"] == [2]
    assert client.ask("total liability fees paid")["found"] is True
    assert client.playbooks()[0]["key"] == "test_pb"
    assert client.providers()["default"] == "openai"
    assert client.health() == {"status": "ok"}

    state, job = client.start_audit(document_id, "test_pb")
    assert state == "running"
    report = _wait(client, job["audit_id"])
    assert report["risk_score"] == 40.0
    state, cached = client.start_audit(document_id, "test_pb")
    assert state == "done" and cached["cached"] is True

    assert client.audits(document_id)[0]["audit_id"] == job["audit_id"]
    assert client.audits() == client.audits(document_id)
    assert client.trace(job["audit_id"])
    review = client.review(job["audit_id"], "liability_cap", "rejected", "wrong clause")
    assert review["decision"] == "rejected"
    assert client.export(job["audit_id"], "pdf").startswith(b"%PDF")
    assert b'"audit_id"' in client.export(job["audit_id"], "json")
    assert client.benchmarks() == []


def test_errors_carry_the_server_detail(api):
    client = ApiClient(api)
    with pytest.raises(ApiError) as info:
        client.start_audit("0" * 64, "test_pb")
    assert info.value.status == 404
    assert info.value.detail == f"document {'0' * 64} not found"

    with pytest.raises(ApiError) as info:
        client.search("")
    assert info.value.status == 422
    assert info.value.detail.startswith("query: ")


def test_unreachable_api_is_status_zero():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    client = ApiClient(httpx.Client(base_url="http://api.invalid", transport=httpx.MockTransport(refuse)))
    with pytest.raises(ApiError) as info:
        client.documents()
    assert info.value.status == 0
    assert info.value.detail.startswith("API unreachable at http://api.invalid")


def test_non_json_error_body_is_used_as_text():
    transport = httpx.MockTransport(lambda request: httpx.Response(502, text="Bad Gateway"))
    client = ApiClient(httpx.Client(base_url="http://proxy", transport=transport))
    with pytest.raises(ApiError) as info:
        client.playbooks()
    assert (info.value.status, info.value.detail) == (502, "Bad Gateway")


def test_read_timeout_is_not_reported_as_unreachable():
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    client = ApiClient(httpx.Client(base_url="http://api.local", transport=httpx.MockTransport(slow)))
    with pytest.raises(ApiError) as info:
        client.documents()
    assert info.value.status == 0
    assert info.value.detail == ("API did not answer within the time limit (http://api.local); "
                                 "it may still be working")
