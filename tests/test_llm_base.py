import pytest
from fakes import FakeLLM, sequence
from pydantic import BaseModel

from auditor.llm.base import LLMError, Usage, complete_with_retry, models_label


class Answer(BaseModel):
    text: str


def test_usage_adds_up():
    assert Usage(10, 2, 0.5) + Usage(5, 1, 0.25) == Usage(15, 3, 0.75)


def test_retry_recovers_from_one_failure():
    llm = FakeLLM({"Answer": sequence(LLMError("bad json"), Answer(text="ok"))})
    result = complete_with_retry(llm, "sys", "user", Answer, "small")
    assert result.value.text == "ok"
    assert result.model == "fake-small"
    assert llm.count("Answer") == 2


def test_retry_gives_up_after_two_attempts():
    llm = FakeLLM({"Answer": LLMError("down")})
    with pytest.raises(LLMError, match="down"):
        complete_with_retry(llm, "sys", "user", Answer, "eval")
    assert llm.count("Answer") == 2


def test_other_exceptions_are_not_retried():
    llm = FakeLLM({"Answer": RuntimeError("bug")})
    with pytest.raises(RuntimeError):
        complete_with_retry(llm, "sys", "user", Answer, "eval")
    assert llm.count("Answer") == 1


def test_missing_fake_handler_is_an_llm_error():
    with pytest.raises(LLMError, match="Answer"):
        FakeLLM().complete("sys", "user", Answer, "eval")


def test_models_label():
    assert models_label(FakeLLM()) == "fake-eval+fake-small"
