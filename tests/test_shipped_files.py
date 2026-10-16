from pathlib import Path

import yaml

from auditor.audit.playbook import load_playbook

ROOT = Path(__file__).parents[1]


def test_commercial_playbook():
    loaded = load_playbook(ROOT / "playbooks" / "commercial_contract.yaml")
    rules = loaded.playbook.rules
    assert len(rules) == 18
    assert {r.type for r in rules} == {"must_exist", "must_not_exist", "condition"}
    assert {"liability_cap", "termination_notice", "governing_law", "confidentiality",
            "unlimited_liability"} <= {r.id for r in rules}
    assert all(len(r.queries) >= 2 for r in rules)


def test_gdpr_playbook():
    loaded = load_playbook(ROOT / "playbooks" / "gdpr_dpa.yaml")
    rules = loaded.playbook.rules
    assert len(rules) == 12
    assert {r.type for r in rules} == {"must_exist", "must_not_exist", "condition"}
    assert all("Art." in r.criteria or "Chapter V" in r.criteria for r in rules)


def test_compose_file():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert set(services) == {"qdrant", "api", "ui", "ollama"}
    assert services["qdrant"]["image"] == "qdrant/qdrant:v1.19.1"
    api = services["api"]
    assert api["environment"]["QDRANT_URL"] == "http://qdrant:6333"
    assert api["environment"]["AUDITOR_DATA_DIR"] == "/data"
    assert api["env_file"] == [{"path": ".env", "required": False}]
    assert "healthcheck" in api
    assert services["ui"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["ui"]["environment"]["AUDITOR_API_URL"] == "http://api:8000"
    assert services["ollama"]["profiles"] == ["local"]
    assert {"auditor-data", "models", "qdrant-data", "ollama"} <= set(compose["volumes"])


def test_dockerfile_runs_the_api_factory():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert text.startswith("FROM python:3.12-slim")
    assert '"--factory", "auditor.api.main:create_app"' in text
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert {".env", ".venv", "data"} <= set(ignored)


def test_compose_ollama_host_is_not_taken_from_the_host_env():
    # .env.example sets OLLAMA_HOST=http://localhost:11434 for running on the host; inside the
    # container localhost is the container itself, so compose must not substitute that variable.
    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    compose = yaml.safe_load(compose_text)
    assert compose["services"]["api"]["environment"]["OLLAMA_HOST"] == "${DOCKER_OLLAMA_HOST:-http://ollama:11434}"
    assert "${OLLAMA_HOST" not in compose_text
