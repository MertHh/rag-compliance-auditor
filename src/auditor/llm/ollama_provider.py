import httpx
import ollama
from pydantic import ValidationError

from auditor.config import Settings
from auditor.llm.base import LLMError, LLMResult, ProviderUnavailableError, T, Tier, Usage

_CALL_ERRORS = (ConnectionError, httpx.HTTPError, ollama.ResponseError)


class OllamaProvider:
    name = "ollama"

    def __init__(self, client, model: str, host: str, num_ctx: int = 16384,
                 think: bool | None = None):
        self._client = client
        self._model = model
        self._host = host
        self._num_ctx = num_ctx
        self._think = think

    @classmethod
    def from_settings(cls, settings: Settings) -> "OllamaProvider":
        client = ollama.Client(host=settings.ollama_host, timeout=600)
        return cls(client, settings.ollama_model, settings.ollama_host, settings.ollama_num_ctx,
                   settings.ollama_think)

    def model_for(self, tier: Tier) -> str:
        return self._model

    def check_available(self) -> None:
        try:
            listed = self._client.list()
        except _CALL_ERRORS as exc:
            raise ProviderUnavailableError(f"Ollama is not reachable at {self._host}: {exc}") from exc
        names = {model.model for model in listed.models}
        if self._model not in names and f"{self._model}:latest" not in names:
            raise ProviderUnavailableError(
                f"Ollama model {self._model!r} is not pulled; run: ollama pull {self._model}"
            )

    def complete(self, system: str, user: str, schema: type[T], tier: Tier) -> LLMResult[T]:
        try:
            extra = {} if self._think is None else {"think": self._think}
            response = self._client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                format=schema.model_json_schema(),
                options={"temperature": 0, "num_ctx": self._num_ctx},
                **extra,
            )
            value = schema.model_validate_json(response.message.content or "")
        except (*_CALL_ERRORS, ValidationError) as exc:
            raise LLMError(f"{self._model}: {exc}") from exc
        usage = Usage(response.prompt_eval_count or 0, response.eval_count or 0, 0.0)
        return LLMResult(value, self._model, usage)
