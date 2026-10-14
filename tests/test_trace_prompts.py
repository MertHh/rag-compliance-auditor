import threading

import pytest

from auditor.audit.playbook import Rule
from auditor.audit.prompts import evaluate_prompt, relevance_prompt, rewrite_prompt
from auditor.audit.trace import TraceRecorder
from auditor.llm.base import LLMResult, Usage
from auditor.retrieval.pipeline import ParentPassage

RULE = Rule(id="unlimited_liability", title="Unlimited liability", type="must_not_exist",
            severity="high", queries=["unlimited liability"], criteria="Liability is uncapped.")
PASSAGE = ParentPassage("p1", "d1", "3.1 The total liability shall not exceed the fees.", 0, 50, "3 > 3.1", [])


def test_recorder_captures_node_usage_and_output():
    recorder = TraceRecorder()
    with recorder.node("r1", "evaluate", "2 sections") as span:
        span.add(LLMResult(None, "m-eval", Usage(100, 20, 0.01)))
        span.add(LLMResult(None, "m-eval", Usage(50, 5, 0.02)))
        span.output = "found"
    [event] = recorder.events()
    assert (event.rule_id, event.node, event.input, event.output) == ("r1", "evaluate", "2 sections", "found")
    assert event.models == ["m-eval"]
    assert (event.input_tokens, event.output_tokens) == (150, 25)
    assert event.cost_usd == pytest.approx(0.03)
    assert event.duration_s >= 0
    assert event.started_at.endswith("+00:00")
    assert recorder.to_dicts()[0]["node"] == "evaluate"


def test_recorder_keeps_failed_nodes():
    recorder = TraceRecorder()
    with pytest.raises(RuntimeError):
        with recorder.node("r1", "search", "q"):
            raise RuntimeError("store down")
    [event] = recorder.events()
    assert event.output == "error: store down"


def test_recorder_totals_across_threads():
    recorder = TraceRecorder()

    def work(i):
        with recorder.node(f"r{i}", "evaluate", "") as span:
            span.add(LLMResult(None, "m", Usage(10, 1, 0.001)))

    threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    totals = recorder.totals()
    assert len(recorder.events()) == 20
    assert (totals.input_tokens, totals.output_tokens) == (200, 20)
    assert totals.cost_usd == pytest.approx(0.02)


def test_evaluate_prompt_carries_rule_and_sections():
    prompt = evaluate_prompt(RULE, [PASSAGE])
    assert prompt.startswith("Rule: Unlimited liability\n")
    assert "must NOT contain" in prompt
    assert "Criteria: Liability is uncapped." in prompt
    assert "[Section 1: 3 > 3.1]" in prompt
    assert "shall not exceed the fees" in prompt


def test_rewrite_and_relevance_prompts():
    assert "- unlimited liability\n- uncapped damages" in rewrite_prompt(RULE, ["unlimited liability", "uncapped damages"])
    prompt = relevance_prompt(RULE, PASSAGE)
    assert prompt.startswith("Rule: Unlimited liability\n")
    assert "[Section 1: 3 > 3.1]" in prompt
