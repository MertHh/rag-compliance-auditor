from datetime import datetime, timezone

from auditor.audit.nodes import RuleState
from auditor.audit.playbook import Rule
from auditor.audit.scoring import Status, risk_score, rule_risk
from auditor.llm.base import LLMProvider, Usage, models_label


def build_finding(rule: Rule, outcome: RuleState | BaseException) -> dict:
    if isinstance(outcome, BaseException):
        error: str | None = f"{type(outcome).__name__}: {outcome}"
        status, reasoning, citations, tried, examined = Status.ERROR, "", [], [], []
    else:
        error = outcome.get("error")
        evaluation = outcome.get("evaluation")
        status = Status.ERROR if error else outcome["status"]
        reasoning = evaluation.reasoning if evaluation is not None and not error else ""
        citations = [] if error else outcome["citations"]
        tried, examined = outcome["tried"], outcome["examined"]
    return {
        "rule_id": rule.id,
        "title": rule.title,
        "type": rule.type,
        "status": status.value,
        "severity": rule.severity,
        "risk": rule_risk(rule.severity, status),
        "reasoning": reasoning,
        "citations": [citation.to_dict() for citation in citations],
        "evidence": {"queries_tried": len(tried), "sections_examined": len(examined)},
        "error": error,
        "review": None,
    }


def build_report(*, audit_id: str, document_id: str, playbook_key: str, provider: LLMProvider,
                 findings: list[dict], duration_s: float, usage: Usage) -> dict:
    return {
        "audit_id": audit_id,
        "document_id": document_id,
        "playbook": playbook_key,
        "provider": provider.name,
        "model": models_label(provider),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "risk_score": risk_score([(f["severity"], Status(f["status"])) for f in findings]),
        "cached": False,
        "findings": findings,
        "errors": [{"rule_id": f["rule_id"], "message": f["error"]}
                   for f in findings if f["status"] == Status.ERROR],
        "totals": {
            "duration_s": round(duration_s, 1),
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": round(usage.cost_usd, 4),
        },
    }
