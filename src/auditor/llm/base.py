from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel

Tier = Literal["eval", "small"]
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """An LLM call failed or returned output that does not fit the schema."""


class ProviderUnavailableError(Exception):
    """The provider cannot be used at all: missing key, server down, model not pulled."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cost_usd + other.cost_usd,
        )


@dataclass
class LLMResult(Generic[T]):
    value: T
    model: str
    usage: Usage


class LLMProvider(Protocol):
    name: str

    def model_for(self, tier: Tier) -> str: ...

    def check_available(self) -> None: ...

    def complete(self, system: str, user: str, schema: type[T], tier: Tier) -> LLMResult[T]: ...


def complete_with_retry(provider: LLMProvider, system: str, user: str, schema: type[T],
                        tier: Tier, attempts: int = 2) -> LLMResult[T]:
    error: LLMError | None = None
    for _ in range(attempts):
        try:
            return provider.complete(system, user, schema, tier)
        except LLMError as exc:
            error = exc
    assert error is not None
    raise error


def models_label(provider: LLMProvider) -> str:
    eval_model, small_model = provider.model_for("eval"), provider.model_for("small")
    return eval_model if eval_model == small_model else f"{eval_model}+{small_model}"
