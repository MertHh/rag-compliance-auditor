from fakes import FakeLLM, fake_services
from fastapi.testclient import TestClient

from auditor.api.main import create_app
from auditor.audit.playbook import PlaybookError, PlaybookNotFound
from auditor.index.store import InvalidDateError
from auditor.llm.base import LLMError, ProviderUnavailableError
from auditor.storage.docstore import DocumentNotFound


def test_health(api):
    assert api.get("/health").json() == {"status": "ok"}


def test_playbooks_lists_valid_and_broken_files(api, playbooks_dir):
    (playbooks_dir / "broken.yaml").write_text("name: Broken\nrules: []\n", encoding="utf-8")
    broken, valid = api.get("/playbooks").json()
    assert broken["key"] == "broken" and broken["rule_count"] == 0
    assert "rules" in broken["error"]
    assert valid == {"key": "test_pb", "name": "Test playbook", "rule_count": 2, "error": None}


def test_providers_report_models(api):
    body = api.get("/providers").json()
    assert body["default"] == "openai"
    assert [p["name"] for p in body["providers"]] == ["openai", "ollama"]
    assert body["providers"][0] == {"name": "openai", "available": True,
                                    "models": "fake-eval+fake-small", "error": None}


def test_unavailable_provider_is_reported_not_raised(tmp_path, playbooks_dir):
    services = fake_services(tmp_path, playbooks_dir, FakeLLM(unavailable="OPENAI_API_KEY is not set"))
    with TestClient(create_app(services)) as client:
        first = client.get("/providers").json()["providers"][0]
    assert first == {"name": "openai", "available": False, "models": None,
                     "error": "OPENAI_API_KEY is not set"}


def _raiser(exc):
    def route():
        raise exc
    return route


def test_core_errors_map_to_status_codes(api_services):
    app = create_app(api_services)
    cases = {
        "document": (DocumentNotFound("abc"), 404, "document abc not found"),
        "playbook": (PlaybookNotFound("playbook 'x' not found; available: a"), 404,
                     "playbook 'x' not found; available: a"),
        "yaml": (PlaybookError("x.yaml: invalid YAML"), 422, "x.yaml: invalid YAML"),
        "date": (InvalidDateError("date must be YYYY-MM-DD, got '2024'"), 422,
                 "date must be YYYY-MM-DD, got '2024'"),
        "down": (ProviderUnavailableError("Ollama is not reachable"), 503, "Ollama is not reachable"),
        "llm": (LLMError("schema mismatch"), 502, "schema mismatch"),
    }
    for name, (exc, _, _) in cases.items():
        app.add_api_route(f"/boom/{name}", _raiser(exc))
    with TestClient(app) as client:
        for name, (_, status, detail) in cases.items():
            response = client.get(f"/boom/{name}")
            assert (response.status_code, response.json()) == (status, {"detail": detail}), name
