import os
import re

import openai
from openai import OpenAI
from pydantic import ValidationError

from auditor.config import Settings
from auditor.llm.base import LLMError, LLMResult, ProviderUnavailableError, T, Tier, Usage

_EVAL = re.compile(r"^gpt-(\d+)(?:\.(\d+))?$")
_SMALL = re.compile(r"^gpt-(\d+)(?:\.(\d+))?-mini$")


def _newest(model_ids: list[str], pattern: re.Pattern) -> str | None:
    best: tuple[tuple[int, int], str] | None = None
    for model_id in model_ids:
        match = pattern.match(model_id)
        if match:
            version = (int(match.group(1)), int(match.group(2) or 0))
            if best is None or version > best[0]:
                best = (version, model_id)
    return best[1] if best else None


def pick_models(model_ids: list[str]) -> tuple[str, str]:
    eval_model, small_model = _newest(model_ids, _EVAL), _newest(model_ids, _SMALL)
    if not eval_model or not small_model:
        raise ProviderUnavailableError(
            "could not pick OpenAI models from the account; "
            "set OPENAI_EVAL_MODEL and OPENAI_SMALL_MODEL"
        )
    return eval_model, small_model


def parse_prices(raw: str) -> dict[str, tuple[float, float]]:
    """'gpt-5.5=1.25/10,gpt-5.4-mini=0.25/2' -> USD per 1M input and output tokens."""
    prices: dict[str, tuple[float, float]] = {}
    for item in filter(None, (part.strip() for part in raw.split(","))):
        try:
            model, pair = item.split("=", 1)
            price_in, price_out = pair.split("/", 1)
            prices[model.strip()] = (float(price_in), float(price_out))
        except ValueError as exc:
            raise ValueError(f"OPENAI_PRICES entry must look like model=in/out, got {item!r}") from exc
    return prices


class OpenAIProvider:
    name = "openai"

    def __init__(self, client, eval_model: str, small_model: str,
                 prices: dict[str, tuple[float, float]] | None = None):
        self._client = client
        self._eval = eval_model
        self._small = small_model
        self._prices = prices or {}

    @classmethod
    def from_settings(cls, settings: Settings) -> "OpenAIProvider":
        if not os.environ.get("OPENAI_API_KEY"):
            raise ProviderUnavailableError("OPENAI_API_KEY is not set")
        client = OpenAI(timeout=120, max_retries=2)
        eval_model, small_model = settings.openai_eval_model, settings.openai_small_model
        if not eval_model or not small_model:
            try:
                model_ids = [model.id for model in client.models.list()]
            except openai.OpenAIError as exc:
                raise ProviderUnavailableError(f"cannot list OpenAI models: {exc}") from exc
            picked_eval, picked_small = pick_models(model_ids)
            eval_model, small_model = eval_model or picked_eval, small_model or picked_small
        return cls(client, eval_model, small_model, parse_prices(settings.openai_prices))

    def model_for(self, tier: Tier) -> str:
        return self._eval if tier == "eval" else self._small

    def check_available(self) -> None:
        # The key and the model names are checked when the provider is built.
        return None

    def complete(self, system: str, user: str, schema: type[T], tier: Tier) -> LLMResult[T]:
        model = self.model_for(tier)
        try:
            response = self._client.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
            )
        except (openai.OpenAIError, ValidationError) as exc:
            raise LLMError(f"{model}: {exc}") from exc
        message = response.choices[0].message
        if message.parsed is None:
            raise LLMError(f"{model}: no structured output ({message.refusal or 'empty response'})")
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0
        price_in, price_out = self._prices.get(model, (0.0, 0.0))
        cost = (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
        return LLMResult(message.parsed, model, Usage(prompt_tokens, completion_tokens, cost))
