import threading
from dataclasses import dataclass, field, replace
from typing import TypedDict

from auditor.audit.citations import Citation, verify_quotes
from auditor.audit.playbook import Rule
from auditor.audit.prompts import (
    EVALUATE_SYSTEM,
    RELEVANCE_SYSTEM,
    REWRITE_SYSTEM,
    Evaluation,
    Relevance,
    RewrittenQueries,
    evaluate_prompt,
    relevance_prompt,
    rewrite_prompt,
)
from auditor.audit.scoring import Status, status_for
from auditor.audit.trace import TraceRecorder
from auditor.index.store import SearchFilter
from auditor.llm.base import LLMError, LLMProvider, complete_with_retry
from auditor.retrieval.config import RetrievalConfig
from auditor.retrieval.pipeline import ParentPassage, RetrievalResult, Retriever
from auditor.storage.docstore import DocumentStore

MAX_NEW_QUERIES = 3


@dataclass(frozen=True)
class AuditConfig:
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    max_rewrites: int = 2
    max_sections: int = 6
    wide_scan_k: int = 15
    concurrency: int = 4


class RuleState(TypedDict, total=False):
    rule: Rule
    queries: list[str]
    tried: list[str]
    rewrites: int
    insufficient: bool
    passages: list[ParentPassage]
    examined: list[str]
    evaluation: Evaluation | None
    eval_attempts: int
    citations: list[Citation]
    needs_retry: bool
    wide_scan_done: bool
    status: Status | None
    error: str | None


def initial_state(rule: Rule) -> RuleState:
    return RuleState(
        rule=rule, queries=list(rule.queries), tried=[], rewrites=0, insufficient=False,
        passages=[], examined=[], evaluation=None, eval_attempts=0, citations=[],
        needs_retry=False, wide_scan_done=False, status=None, error=None,
    )


def _round_robin(results: list[RetrievalResult], limit: int) -> list[ParentPassage]:
    """Take each query's best section in turn so one query cannot crowd out the others."""
    merged: dict[str, ParentPassage] = {}
    depth = max((len(r.parents) for r in results), default=0)
    for i in range(depth):
        for result in results:
            if i < len(result.parents):
                merged.setdefault(result.parents[i].parent_id, result.parents[i])
    return list(merged.values())[:limit]


def _add_examined(examined: list[str], passages: list[ParentPassage]) -> list[str]:
    added = [p.parent_id for p in passages if p.parent_id not in examined]
    return examined + list(dict.fromkeys(added))


class RuleNodes:
    def __init__(self, retriever: Retriever, docstore: DocumentStore, provider: LLMProvider,
                 recorder: TraceRecorder, document_id: str, config: AuditConfig,
                 lock: threading.Lock):
        self._retriever = retriever
        self._docstore = docstore
        self._provider = provider
        self._recorder = recorder
        self._document_id = document_id
        self._config = config
        self._lock = lock
        self._filter = SearchFilter(document_ids=[document_id])

    def _search(self, query: str, config: RetrievalConfig) -> RetrievalResult:
        with self._lock:
            return self._retriever.search(query, config, self._filter)

    def search(self, state: RuleState) -> dict:
        rule, queries = state["rule"], state["queries"]
        with self._recorder.node(rule.id, "search", "; ".join(queries)) as span:
            results = [self._search(query, self._config.retrieval) for query in queries]
            found = _round_robin(results, self._config.max_sections)
            combined: dict[str, ParentPassage] = {}
            for passage in [*found, *state["passages"]]:
                combined.setdefault(passage.parent_id, passage)
            passages = list(combined.values())[: self._config.max_sections]
            insufficient = all(result.insufficient_evidence for result in results)
            span.output = f"{len(found)} new sections, insufficient={insufficient}"
        return {
            "passages": passages,
            "tried": state["tried"] + [q for q in queries if q not in state["tried"]],
            "insufficient": insufficient,
        }

    def rewrite(self, state: RuleState) -> dict:
        rule = state["rule"]
        with self._recorder.node(rule.id, "rewrite", "; ".join(state["tried"])) as span:
            try:
                result = complete_with_retry(self._provider, REWRITE_SYSTEM,
                                             rewrite_prompt(rule, state["tried"]),
                                             RewrittenQueries, "small")
            except LLMError as exc:
                span.output = f"error: {exc}"
                return {"error": f"query rewrite failed: {exc}", "rewrites": state["rewrites"] + 1}
            span.add(result)
            fresh = [q.strip() for q in result.value.queries if q.strip()]
            queries = [q for q in dict.fromkeys(fresh) if q not in state["tried"]][:MAX_NEW_QUERIES]
            span.output = "; ".join(queries) or "no new queries"
        return {"queries": queries, "rewrites": state["rewrites"] + 1}

    def evaluate(self, state: RuleState) -> dict:
        rule, passages = state["rule"], state["passages"]
        examined = _add_examined(state["examined"], passages)
        attempts = state["eval_attempts"] + 1
        with self._recorder.node(rule.id, "evaluate", f"{len(passages)} sections") as span:
            if not passages:
                span.output = "no sections retrieved"
                evaluation = Evaluation(clause_found=False, matches_criteria=False, quotes=[],
                                        reasoning="No candidate sections were retrieved for this rule.")
                return {"evaluation": evaluation, "eval_attempts": attempts, "examined": examined}
            try:
                result = complete_with_retry(self._provider, EVALUATE_SYSTEM,
                                             evaluate_prompt(rule, passages), Evaluation, "eval")
            except LLMError as exc:
                span.output = f"error: {exc}"
                return {"error": f"evaluation failed: {exc}", "examined": examined}
            span.add(result)
            evaluation = result.value
            span.output = (f"found={evaluation.clause_found} matches={evaluation.matches_criteria} "
                           f"quotes={len(evaluation.quotes)}")
        return {"evaluation": evaluation, "eval_attempts": attempts, "examined": examined}

    def verify(self, state: RuleState) -> dict:
        rule, evaluation = state["rule"], state["evaluation"]
        with self._recorder.node(rule.id, "verify", f"{len(evaluation.quotes)} quotes") as span:
            if not evaluation.clause_found:
                status = status_for(rule.type, False, False)
                span.output = f"no clause claimed, status={status}"
                return {"citations": [], "needs_retry": False, "status": status}
            with self._lock:
                doc = self._docstore.load(self._document_id)
            citations = verify_quotes(doc, evaluation.quotes, state["passages"])
            if not citations:
                if state["eval_attempts"] < 2:
                    span.output = "no verified quote, evaluating again"
                    return {"citations": [], "needs_retry": True}
                span.output = "no verified quote after retry"
                return {"citations": [], "needs_retry": False, "status": Status.UNCERTAIN}
            status = status_for(rule.type, True, evaluation.matches_criteria)
            span.output = f"{len(citations)} verified, status={status}"
        return {"citations": citations, "needs_retry": False, "status": status}

    def wide_scan(self, state: RuleState) -> dict:
        rule = state["rule"]
        k = self._config.wide_scan_k
        config = replace(self._config.retrieval, final_k=k)
        with self._recorder.node(rule.id, "wide_scan", f"top {k} sections") as span:
            candidates = _round_robin([self._search(q, config) for q in state["tried"]], k)
            relevant: list[ParentPassage] = []
            try:
                for passage in candidates:
                    result = complete_with_retry(self._provider, RELEVANCE_SYSTEM,
                                                 relevance_prompt(rule, passage), Relevance, "small")
                    span.add(result)
                    if result.value.relevant:
                        relevant.append(passage)
            except LLMError as exc:
                span.output = f"error: {exc}"
                return {"error": f"wide scan failed: {exc}", "wide_scan_done": True}
            span.output = f"{len(relevant)} of {len(candidates)} sections relevant"
        update: dict = {"wide_scan_done": True,
                        "examined": _add_examined(state["examined"], candidates)}
        if relevant:
            cited = [p for p in state["passages"]
                     if any(p.document_id == c.document_id and p.char_start <= c.char_start < p.char_end
                            for c in state["citations"])]
            merged = list({p.parent_id: p for p in cited + relevant}.values())
            update.update(passages=merged[: self._config.max_sections], evaluation=None,
                          eval_attempts=0, status=None, citations=[])
        return update
