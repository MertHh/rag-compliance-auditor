from fakes import LIABILITY_LINE, FakeLLM, fake_services
from fastapi.testclient import TestClient

from auditor.api.main import create_app
from auditor.llm.base import LLMError


def _ingest(services, contract_pdf) -> str:
    return services.indexer.ingest_pdf(contract_pdf).document_id


def test_search_returns_stage_scores_and_boxes(api, api_services, contract_pdf):
    document_id = _ingest(api_services, contract_pdf)
    body = api.post("/search", json={"query": "total liability fees", "final_k": 1}).json()
    assert body["insufficient_evidence"] is False
    assert body["config"]["mode"] == "hybrid" and body["config"]["final_k"] == 1
    [chunk] = body["chunks"]
    assert chunk["document_id"] == document_id
    assert chunk["pages"] == [2]
    assert chunk["bboxes"][0]["page"] == 2 and len(chunk["bboxes"][0]["bbox"]) == 4
    scores = chunk["scores"]
    assert scores["final_rank"] == 1 and scores["rerank_score"] is not None
    assert set(scores) == {"bm25_rank", "bm25_score", "dense_rank", "dense_score", "rrf_score",
                           "fused_rank", "rerank_score", "final_rank", "rank_change"}
    assert body["parents"][0]["chunk_ids"] == [chunk["chunk_id"]]


def test_search_mode_and_filters(api, api_services, contract_pdf, sample_contract):
    pdf_id = _ingest(api_services, contract_pdf)
    api_services.indexer.ingest_text(sample_contract, "other.txt")
    body = api.post("/search", json={"query": "liability", "mode": "bm25", "rerank": False,
                                     "filters": {"document_ids": [pdf_id]}}).json()
    assert body["chunks"]
    assert {c["document_id"] for c in body["chunks"]} == {pdf_id}
    assert all(c["scores"]["dense_rank"] is None and c["scores"]["rerank_score"] is None
               for c in body["chunks"])


def test_search_validation_errors(api):
    assert api.post("/search", json={"query": ""}).status_code == 422
    assert api.post("/search", json={"query": "x", "mode": "fuzzy"}).status_code == 422
    assert api.post("/search", json={"query": "x", "final_k": 0}).status_code == 422
    bad_date = api.post("/search", json={"query": "x", "filters": {"date_from": "March 2024"}})
    assert bad_date.status_code == 422
    assert "YYYY-MM-DD" in str(bad_date.json()["detail"])


def test_ask_answers_with_verified_citation(api, api_services, contract_pdf):
    document_id = _ingest(api_services, contract_pdf)
    body = api.post("/ask", json={"question": "total liability fees paid",
                                  "filters": {"document_ids": [document_id]}}).json()
    assert body["found"] is True
    assert body["answer"] == "Liability is capped at the fees paid in twelve months."
    [citation] = body["citations"]
    assert citation["quote"] == LIABILITY_LINE.rstrip(".") and citation["page"] == 2
    assert body["model"] == "fake-small"
    assert body["usage"]["input_tokens"] == 100


def test_ask_without_evidence_does_not_call_llm(api, api_services, api_llm, contract_pdf):
    _ingest(api_services, contract_pdf)
    api_llm.calls.clear()
    body = api.post("/ask", json={"question": "zebra quantum"}).json()
    assert body["found"] is False
    assert body["message"].startswith("I could not find")
    assert api_llm.calls == []


def test_ask_provider_errors(tmp_path, playbooks_dir, contract_pdf):
    down = fake_services(tmp_path / "a", playbooks_dir, FakeLLM(unavailable="Ollama is not reachable"))
    with TestClient(create_app(down)) as client:
        response = client.post("/ask", json={"question": "liability", "provider": "ollama"})
    assert (response.status_code, response.json()) == (503, {"detail": "Ollama is not reachable"})

    broken = fake_services(tmp_path / "b", playbooks_dir, FakeLLM({"QAOutput": LLMError("bad json")}))
    broken.indexer.ingest_pdf(contract_pdf)
    with TestClient(create_app(broken)) as client:
        response = client.post("/ask", json={"question": "total liability fees paid"})
    assert (response.status_code, response.json()) == (502, {"detail": "bad json"})


def test_ask_rejects_unknown_provider(api):
    assert api.post("/ask", json={"question": "x", "provider": "gemini"}).status_code == 422
