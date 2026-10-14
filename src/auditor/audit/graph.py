from langgraph.graph import END, START, StateGraph

from auditor.audit.nodes import RuleNodes, RuleState
from auditor.audit.scoring import is_absence_verdict


def after_search(state: RuleState, max_rewrites: int) -> str:
    if state["insufficient"] and state["rewrites"] < max_rewrites:
        return "rewrite"
    return "evaluate"


def after_rewrite(state: RuleState) -> str:
    return END if state.get("error") else "search"


def after_evaluate(state: RuleState) -> str:
    return END if state.get("error") else "verify"


def after_verify(state: RuleState) -> str:
    if state["needs_retry"]:
        return "evaluate"
    if is_absence_verdict(state["rule"].type, state["status"]) and not state["wide_scan_done"]:
        return "wide_scan"
    return END


def after_wide_scan(state: RuleState) -> str:
    if state.get("error") or state["status"] is not None:
        return END
    return "evaluate"


def build_rule_graph(nodes: RuleNodes, max_rewrites: int):
    graph = StateGraph(RuleState)
    graph.add_node("search", nodes.search)
    graph.add_node("rewrite", nodes.rewrite)
    graph.add_node("evaluate", nodes.evaluate)
    graph.add_node("verify", nodes.verify)
    graph.add_node("wide_scan", nodes.wide_scan)
    graph.add_edge(START, "search")
    graph.add_conditional_edges("search", lambda s: after_search(s, max_rewrites),
                                ["rewrite", "evaluate"])
    graph.add_conditional_edges("rewrite", after_rewrite, ["search", END])
    graph.add_conditional_edges("evaluate", after_evaluate, ["verify", END])
    graph.add_conditional_edges("verify", after_verify, ["evaluate", "wide_scan", END])
    graph.add_conditional_edges("wide_scan", after_wide_scan, ["evaluate", END])
    return graph.compile()
