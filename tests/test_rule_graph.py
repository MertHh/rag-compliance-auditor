import threading

import pytest
from fakes import FakeEmbedder, FakeLLM, FakeReranker, FakeSparseEncoder, sequence

from auditor.audit.graph import build_rule_graph
from auditor.audit.nodes import AuditConfig, RuleNodes, initial_state
from auditor.audit.playbook import Rule
from auditor.audit.prompts import Evaluation, Relevance, RewrittenQueries
from auditor.audit.scoring import Status
from auditor.audit.trace import TraceRecorder
from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.indexer import Indexer
from auditor.llm.base import LLMError
from auditor.retrieval.pipeline import Retriever
from auditor.storage.docstore import DocumentStore

LIABILITY_QUOTE = ("The total aggregate liability of either party shall not exceed the fees "
                   "paid in the twelve months preceding the claim.")
FOUND = Evaluation(clause_found=True, matches_criteria=True, reasoning="Capped at fees.",
                   quotes=[LIABILITY_QUOTE])
NOT_FOUND = Evaluation(clause_found=False, matches_criteria=False, reasoning="No clause.", quotes=[])
INVENTED = Evaluation(clause_found=True, matches_criteria=True, reasoning="Invented.",
                      quotes=["Liability is unlimited for all claims of any kind."])


@pytest.fixture
def env(tmp_path, sample_contract):
    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse = FakeEmbedder(), FakeSparseEncoder()
    doc_id = Indexer(store, embedder, sparse, docstore).ingest_text(sample_contract, "msa.txt").document_id
    return Retriever(store, embedder, sparse, FakeReranker(), docstore), docstore, doc_id


def _rule(rule_type="must_exist", queries=("total aggregate liability",)):
    return Rule(id="liability_cap", title="Liability cap", type=rule_type, severity="high",
                queries=list(queries), criteria="Total liability is capped.")


def _run(env, rule, llm, config=AuditConfig()):
    retriever, docstore, doc_id = env
    recorder = TraceRecorder()
    nodes = RuleNodes(retriever, docstore, llm, recorder, doc_id, config, threading.Lock())
    final = build_rule_graph(nodes, config.max_rewrites).invoke(initial_state(rule))
    return final, [event.node for event in recorder.events()]


def test_found_clause_with_verified_quote_is_compliant(env):
    llm = FakeLLM({"Evaluation": FOUND})
    final, nodes = _run(env, _rule(), llm)
    assert final["status"] is Status.COMPLIANT
    assert nodes == ["search", "evaluate", "verify"]
    [citation] = final["citations"]
    assert citation.quote.startswith("The total aggregate liability")
    assert citation.section_path.startswith("3")
    assert final["tried"] == ["total aggregate liability"]
    assert len(final["examined"]) >= 1
    assert llm.calls[0][1] == "eval"
    assert "Rule: Liability cap" in llm.calls[0][2]


def test_invented_quote_twice_is_uncertain(env):
    llm = FakeLLM({"Evaluation": INVENTED})
    final, nodes = _run(env, _rule(), llm)
    assert final["status"] is Status.UNCERTAIN
    assert final["citations"] == []
    assert llm.count("Evaluation") == 2
    assert nodes == ["search", "evaluate", "verify", "evaluate", "verify"]


def test_invented_quote_then_real_quote_is_compliant(env):
    llm = FakeLLM({"Evaluation": sequence(INVENTED, FOUND)})
    final, _ = _run(env, _rule(), llm)
    assert final["status"] is Status.COMPLIANT
    assert len(final["citations"]) == 1


def test_missing_clause_triggers_wide_scan(env):
    llm = FakeLLM({"Evaluation": NOT_FOUND, "Relevance": Relevance(relevant=False)})
    final, nodes = _run(env, _rule(), llm)
    assert final["status"] is Status.MISSING
    assert nodes == ["search", "evaluate", "verify", "wide_scan"]
    assert llm.count("Relevance") >= 1
    assert all(tier == "small" for name, tier, _ in llm.calls if name == "Relevance")
    assert len(final["examined"]) >= llm.count("Relevance")


def test_wide_scan_finding_relevant_section_reevaluates(env):
    relevant = lambda user: Relevance(relevant="aggregate liability" in user)
    llm = FakeLLM({"Evaluation": sequence(NOT_FOUND, FOUND), "Relevance": relevant})
    final, nodes = _run(env, _rule(), llm)
    assert final["status"] is Status.COMPLIANT
    assert nodes == ["search", "evaluate", "verify", "wide_scan", "evaluate", "verify"]
    second_prompt = [user for name, _, user in llm.calls if name == "Evaluation"][1]
    assert "aggregate liability" in second_prompt


def test_insufficient_evidence_rewrites_twice_then_evaluates(env):
    llm = FakeLLM({
        "RewrittenQueries": sequence(RewrittenQueries(queries=["zebra galaxy"]),
                                     RewrittenQueries(queries=["zebra nebula", "zebra galaxy"])),
        "Evaluation": NOT_FOUND,
        "Relevance": Relevance(relevant=False),
    })
    final, nodes = _run(env, _rule(queries=["zebra quantum"]), llm)
    assert llm.count("RewrittenQueries") == 2
    assert final["tried"] == ["zebra quantum", "zebra galaxy", "zebra nebula"]
    assert nodes[:6] == ["search", "rewrite", "search", "rewrite", "search", "evaluate"]
    assert final["status"] is Status.MISSING
    assert "- zebra quantum\n- zebra galaxy" in [u for n, _, u in llm.calls if n == "RewrittenQueries"][1]


def test_rewrite_that_finds_evidence_stops_rewriting(env):
    llm = FakeLLM({
        "RewrittenQueries": RewrittenQueries(queries=["total aggregate liability fees paid"]),
        "Evaluation": FOUND,
    })
    final, nodes = _run(env, _rule(queries=["zebra quantum"]), llm)
    assert llm.count("RewrittenQueries") == 1
    assert nodes == ["search", "rewrite", "search", "evaluate", "verify"]
    assert final["status"] is Status.COMPLIANT


def test_llm_failure_sets_error_after_retry(env):
    llm = FakeLLM({"Evaluation": LLMError("timeout")})
    final, nodes = _run(env, _rule(), llm)
    assert "evaluation failed" in final["error"]
    assert final["status"] is None
    assert llm.count("Evaluation") == 2
    assert nodes == ["search", "evaluate"]


def test_prohibited_clause_absent_is_compliant_after_wide_scan(env):
    llm = FakeLLM({"Evaluation": NOT_FOUND, "Relevance": Relevance(relevant=False)})
    final, nodes = _run(env, _rule("must_not_exist"), llm)
    assert final["status"] is Status.COMPLIANT
    assert nodes[-1] == "wide_scan"


def test_prohibited_clause_present_is_non_compliant_without_wide_scan(env):
    llm = FakeLLM({"Evaluation": FOUND})
    final, nodes = _run(env, _rule("must_not_exist"), llm)
    assert final["status"] is Status.NON_COMPLIANT
    assert "wide_scan" not in nodes


def test_section_cap_limits_evaluated_passages(env):
    llm = FakeLLM({"Evaluation": FOUND})
    final, _ = _run(env, _rule(queries=["agreement", "party", "liability"]), llm,
                    AuditConfig(max_sections=2))
    assert len(final["passages"]) == 2


BENIGN = Evaluation(clause_found=True, matches_criteria=False, reasoning="Benign.",
                    quotes=[LIABILITY_QUOTE])


def test_prohibited_clause_found_but_not_matching_still_wide_scans(env):
    llm = FakeLLM({"Evaluation": BENIGN, "Relevance": Relevance(relevant=False)})
    final, nodes = _run(env, _rule("must_not_exist"), llm)
    assert final["status"] is Status.COMPLIANT
    assert len(final["citations"]) == 1
    assert nodes == ["search", "evaluate", "verify", "wide_scan"]


def test_wide_scan_reevaluation_keeps_cited_section(env):
    relevant = lambda user: Relevance(relevant="aggregate liability" not in user)  # not the cited section
    llm = FakeLLM({"Evaluation": BENIGN, "Relevance": relevant})
    final, nodes = _run(env, _rule("must_not_exist"), llm)
    assert nodes[:4] == ["search", "evaluate", "verify", "wide_scan"]
    assert llm.count("Evaluation") == 2
    second_prompt = [user for name, _, user in llm.calls if name == "Evaluation"][1]
    assert LIABILITY_QUOTE in second_prompt


def test_rewrite_failure_sets_error(env):
    llm = FakeLLM({"RewrittenQueries": LLMError("down")})
    final, nodes = _run(env, _rule(queries=["zebra quantum"]), llm)
    assert "query rewrite failed" in final["error"]
    assert final["status"] is None
    assert nodes == ["search", "rewrite"]
    assert llm.count("RewrittenQueries") == 2


def test_wide_scan_failure_sets_error(env):
    llm = FakeLLM({"Evaluation": NOT_FOUND, "Relevance": LLMError("down")})
    final, nodes = _run(env, _rule(), llm)
    assert "wide scan failed" in final["error"]
    assert nodes[-1] == "wide_scan"


def test_evaluation_failure_after_wide_scan_sets_error(env):
    llm = FakeLLM({"Evaluation": sequence(NOT_FOUND, LLMError("down")),
                   "Relevance": Relevance(relevant=True)})
    final, nodes = _run(env, _rule(), llm)
    assert "evaluation failed" in final["error"]
    assert final["status"] is None
