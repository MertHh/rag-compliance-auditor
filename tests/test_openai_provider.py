from dataclasses import replace
from types import SimpleNamespace

import openai
import pytest
from pydantic import BaseModel

from auditor.config import Settings
from auditor.llm import openai_provider
from auditor.llm.base import LLMError, ProviderUnavailableError
from auditor.llm.openai_provider import OpenAIProvider, parse_prices, pick_models

ACCOUNT_MODELS = [
    "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-5", "gpt-5-mini", "gpt-5.4",
    "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.5", "gpt-5.5-pro", "gpt-5.5-2026-04-23",
    "gpt-6-sol", "gpt-6.1-sol", "gpt-image-2", "gpt-realtime-2.1-mini", "whisper-1",
]


class Verdict(BaseModel):
    ok: bool


class FakeCompletions:
    def __init__(self, outcome):
        self.outcome = outcome
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _client(outcome=None, models=ACCOUNT_MODELS):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions(outcome)),
        models=SimpleNamespace(list=lambda: [SimpleNamespace(id=m) for m in models]),
    )


def _response(parsed, refusal=None, prompt_tokens=1000, completion_tokens=200):
    message = SimpleNamespace(parsed=parsed, refusal=refusal)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def _settings(**overrides):
    return replace(Settings.from_env(), **overrides)


def test_pick_models_takes_newest_numbered_and_mini():
    assert pick_models(ACCOUNT_MODELS) == ("gpt-5.5", "gpt-5.4-mini")


def test_pick_models_fails_without_candidates():
    with pytest.raises(ProviderUnavailableError, match="OPENAI_EVAL_MODEL"):
        pick_models(["gpt-image-2", "whisper-1"])


def test_parse_prices():
    assert parse_prices("gpt-5.5=1.25/10, gpt-5.4-mini=0.25/2") == {
        "gpt-5.5": (1.25, 10.0),
        "gpt-5.4-mini": (0.25, 2.0),
    }
    assert parse_prices("") == {}
    with pytest.raises(ValueError, match="model=in/out"):
        parse_prices("gpt-5.5:1.25")


def test_complete_returns_value_usage_and_cost():
    client = _client(_response(Verdict(ok=True)))
    provider = OpenAIProvider(client, "gpt-5.5", "gpt-5.4-mini", {"gpt-5.4-mini": (0.25, 2.0)})
    result = provider.complete("system text", "user text", Verdict, "small")
    assert result.value == Verdict(ok=True)
    assert result.model == "gpt-5.4-mini"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (1000, 200)
    assert result.usage.cost_usd == pytest.approx(0.00065)
    kwargs = client.chat.completions.kwargs
    assert kwargs["model"] == "gpt-5.4-mini"
    assert kwargs["response_format"] is Verdict
    assert kwargs["messages"] == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": "user text"},
    ]


def test_eval_tier_uses_eval_model_and_unknown_price_costs_zero():
    client = _client(_response(Verdict(ok=False)))
    provider = OpenAIProvider(client, "gpt-5.5", "gpt-5.4-mini")
    result = provider.complete("s", "u", Verdict, "eval")
    assert client.chat.completions.kwargs["model"] == "gpt-5.5"
    assert result.usage.cost_usd == 0.0


def test_refusal_is_an_llm_error():
    provider = OpenAIProvider(_client(_response(None, refusal="I can't help")), "gpt-5.5", "gpt-5.4-mini")
    with pytest.raises(LLMError, match="I can't help"):
        provider.complete("s", "u", Verdict, "eval")


def test_sdk_error_is_an_llm_error():
    provider = OpenAIProvider(_client(openai.OpenAIError("rate limited")), "gpt-5.5", "gpt-5.4-mini")
    with pytest.raises(LLMError, match="rate limited"):
        provider.complete("s", "u", Verdict, "eval")


def test_from_settings_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailableError, match="OPENAI_API_KEY"):
        OpenAIProvider.from_settings(_settings())


def test_from_settings_picks_models_from_account(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(openai_provider, "OpenAI", lambda **kwargs: _client())
    provider = OpenAIProvider.from_settings(
        _settings(openai_eval_model=None, openai_small_model=None)
    )
    assert (provider.model_for("eval"), provider.model_for("small")) == ("gpt-5.5", "gpt-5.4-mini")


def test_from_settings_keeps_configured_models(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(openai_provider, "OpenAI", lambda **kwargs: _client(models=[]))
    provider = OpenAIProvider.from_settings(
        _settings(openai_eval_model="gpt-5.4", openai_small_model="gpt-5.4-nano", openai_prices="gpt-5.4=1/8")
    )
    assert (provider.model_for("eval"), provider.model_for("small")) == ("gpt-5.4", "gpt-5.4-nano")
