import threading

import pytest

from auditor.audit.playbook import Rule
from auditor.audit.prompts import Wording, evaluate_prompt, relevance_prompt, rewrite_prompt
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


# The prompts the CUAD benchmarks were measured with, frozen word for word.
CONTRACT_SYSTEM = {'evaluate': "You review contracts against compliance rules. You receive one rule and numbered sections from a single contract. Set clause_found to true if the sections contain a clause on the rule's topic. Set matches_criteria to true if that clause matches the rule's criteria. When the rule says the clause is prohibited, the criteria describe the prohibited clause, and matches_criteria means the text is that prohibited clause. Copy the decisive sentences into quotes word for word from the sections, without changing, joining or shortening them. If clause_found is false, return no quotes and set matches_criteria to false. Explain the decision in reasoning in two or three sentences.", 'rewrite': 'You write search queries for finding a clause in a contract. Return two or three short queries worded differently from the queries that already failed, using synonyms and the terms contracts commonly use for this clause.', 'relevance': "You check whether one contract section is relevant to a compliance rule. Set relevant to true only if the section contains a clause on the rule's topic, whether or not the clause meets the criteria."}
CONTRACT_KIND = {'must_exist': 'The contract must contain this clause.', 'must_not_exist': 'The contract must NOT contain this clause; it is prohibited.', 'condition': 'If the contract has this clause, the clause must meet the criteria.'}


def test_contract_wording_reproduces_the_benchmarked_prompts():
    wording = Wording("contract", "clause")
    assert wording.evaluate_system() == CONTRACT_SYSTEM["evaluate"]
    assert wording.rewrite_system() == CONTRACT_SYSTEM["rewrite"]
    assert wording.relevance_system() == CONTRACT_SYSTEM["relevance"]
    assert {kind: wording.kind(kind) for kind in CONTRACT_KIND} == CONTRACT_KIND


def test_default_wording_names_no_domain():
    wording = Wording()
    texts = [wording.evaluate_system(), wording.rewrite_system(), wording.relevance_system(),
             evaluate_prompt(RULE, [PASSAGE])]
    assert not any("contract" in text or "clause " in text for text in texts)
    assert "The document must NOT contain this passage" in evaluate_prompt(RULE, [PASSAGE])
    paper = Wording("research paper", "statement")
    assert "terms research papers commonly use" in paper.rewrite_system()
    assert "The research paper must NOT contain this statement" in evaluate_prompt(RULE, [PASSAGE], paper)
