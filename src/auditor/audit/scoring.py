from enum import StrEnum


class Status(StrEnum):
    COMPLIANT = "uyumlu"
    NON_COMPLIANT = "uyumsuz"
    MISSING = "eksik"
    UNCERTAIN = "belirsiz"
    ERROR = "hata"


SEVERITY_WEIGHT = {"low": 1, "medium": 2, "high": 3}
STATUS_MULTIPLIER = {
    Status.COMPLIANT: 0.0,
    Status.UNCERTAIN: 0.5,
    Status.NON_COMPLIANT: 1.0,
    Status.MISSING: 1.0,
}


def status_for(rule_type: str, clause_found: bool, matches_criteria: bool) -> Status:
    if rule_type == "must_not_exist":
        return Status.NON_COMPLIANT if clause_found and matches_criteria else Status.COMPLIANT
    if not clause_found:
        return Status.MISSING
    return Status.COMPLIANT if matches_criteria else Status.NON_COMPLIANT


def is_absence_verdict(rule_type: str, status: Status | None) -> bool:
    if status is Status.MISSING:
        return True
    return rule_type == "must_not_exist" and status is Status.COMPLIANT


def rule_risk(severity: str, status: Status) -> float | None:
    if status is Status.ERROR:
        return None
    return SEVERITY_WEIGHT[severity] * STATUS_MULTIPLIER[status]


def risk_score(items: list[tuple[str, Status]]) -> float | None:
    counted = [(SEVERITY_WEIGHT[severity], STATUS_MULTIPLIER[status])
               for severity, status in items if status is not Status.ERROR]
    if not counted:
        return None
    total_weight = sum(weight for weight, _ in counted)
    return round(100 * sum(weight * mult for weight, mult in counted) / total_weight, 1)
