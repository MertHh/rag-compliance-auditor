from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from auditor.config import Settings
from auditor.llm.base import LLMError, ProviderUnavailableError
from auditor.llm.factory import build_provider, cached_provider_factory
from auditor.llm.ollama_provider import OllamaProvider


class Verdict(BaseModel):
    ok: bool


class FakeOllamaClient:
    def __init__(self, models=("qwen3:8b",), content='{"ok": true}', error=None):
        self.models = models
        self.content = content
        self.error = error
        self.kwargs = None

    def list(self):
        if self.error:
            raise self.error
        return SimpleNamespace(models=[SimpleNamespace(model=m) for m in self.models])

    def chat(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(
            message=SimpleNamespace(content=self.content), prompt_eval_count=50, eval_count=7
        )


def _provider(**kwargs):
    client = FakeOllamaClient(**kwargs)
    return OllamaProvider(client, "qwen3:8b", "http://localhost:11434", num_ctx=8192), client


def test_complete_parses_json_with_schema_constraint():
    provider, client = _provider()
    result = provider.complete("system text", "user text", Verdict, "eval")
    assert result.value == Verdict(ok=True)
    assert result.model == "qwen3:8b"
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.cost_usd) == (50, 7, 0.0)
    assert client.kwargs["model"] == "qwen3:8b"
    assert client.kwargs["format"] == Verdict.model_json_schema()
    assert client.kwargs["options"] == {"temperature": 0, "num_ctx": 8192}
    assert client.kwargs["messages"][0] == {"role": "system", "content": "system text"}


def test_both_tiers_use_the_same_model():
    provider, _ = _provider()
    assert provider.model_for("eval") == provider.model_for("small") == "qwen3:8b"


@pytest.mark.parametrize("content", ["not json", '{"ok": "maybe"}', "{}"])
def test_bad_output_is_an_llm_error(content):
    provider, _ = _provider(content=content)
    with pytest.raises(LLMError):
        provider.complete("s", "u", Verdict, "eval")


def test_connection_failure_during_call_is_an_llm_error():
    provider, _ = _provider(error=ConnectionError("Failed to connect to Ollama"))
    with pytest.raises(LLMError, match="Failed to connect"):
        provider.complete("s", "u", Verdict, "eval")


def test_check_available_reports_unreachable_server():
    provider, _ = _provider(error=ConnectionError("Failed to connect to Ollama"))
    with pytest.raises(ProviderUnavailableError, match="not reachable at http://localhost:11434"):
        provider.check_available()


def test_check_available_reports_missing_model():
    provider, _ = _provider(models=("llama3.1:8b",))
    with pytest.raises(ProviderUnavailableError, match="ollama pull qwen3:8b"):
        provider.check_available()


def test_check_available_accepts_latest_tag():
    client = FakeOllamaClient(models=("mistral:latest",))
    OllamaProvider(client, "mistral", "http://h").check_available()


def test_factory_builds_ollama_and_rejects_unknown_names():
    settings = replace(Settings.from_env(), ollama_model="llama3.1:8b")
    provider = build_provider("ollama", settings)
    assert isinstance(provider, OllamaProvider)
    assert provider.model_for("eval") == "llama3.1:8b"
    with pytest.raises(ValueError, match="openai or ollama"):
        build_provider("anthropic", settings)


def test_factory_reports_missing_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailableError, match="OPENAI_API_KEY"):
        build_provider("openai", Settings.from_env())


def test_cached_factory_builds_each_provider_once():
    get = cached_provider_factory(Settings.from_env())
    assert get("ollama") is get("ollama")


def test_think_is_sent_only_when_set():
    provider, client = _provider()
    provider.complete("s", "u", Verdict, "eval")
    assert "think" not in client.kwargs
    client = FakeOllamaClient()
    OllamaProvider(client, "qwen3:8b", "http://h", think=False).complete("s", "u", Verdict, "eval")
    assert client.kwargs["think"] is False
