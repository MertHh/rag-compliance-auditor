import threading
from typing import Callable

from auditor.config import Settings
from auditor.llm.base import LLMProvider
from auditor.llm.ollama_provider import OllamaProvider
from auditor.llm.openai_provider import OpenAIProvider

PROVIDERS = ("openai", "ollama")


def build_provider(name: str, settings: Settings) -> LLMProvider:
    if name == "openai":
        return OpenAIProvider.from_settings(settings)
    if name == "ollama":
        return OllamaProvider.from_settings(settings)
    raise ValueError(f"unknown provider {name!r}; choose openai or ollama")


def cached_provider_factory(settings: Settings) -> Callable[[str], LLMProvider]:
    providers: dict[str, LLMProvider] = {}
    lock = threading.Lock()

    def get(name: str) -> LLMProvider:
        with lock:
            if name not in providers:
                providers[name] = build_provider(name, settings)
            return providers[name]

    return get
