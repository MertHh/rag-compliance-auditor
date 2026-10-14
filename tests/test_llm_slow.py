import pytest
from dotenv import load_dotenv
from pydantic import BaseModel

from auditor.config import Settings
from auditor.llm.base import ProviderUnavailableError
from auditor.llm.factory import build_provider

pytestmark = pytest.mark.slow


class Capital(BaseModel):
    city: str


@pytest.mark.parametrize("name", ["openai", "ollama"])
def test_real_provider_returns_schema_output(name):
    load_dotenv()
    try:
        provider = build_provider(name, Settings.from_env())
        provider.check_available()
    except ProviderUnavailableError as exc:
        pytest.skip(str(exc))
    result = provider.complete(
        "Answer with the requested JSON.", "What is the capital of France?", Capital, "small"
    )
    assert "paris" in result.value.city.lower()
    assert result.usage.input_tokens > 0
