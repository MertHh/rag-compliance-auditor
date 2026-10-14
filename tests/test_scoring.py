import pytest

from auditor.audit.scoring import Status, is_absence_verdict, risk_score, rule_risk, status_for

S = Status


@pytest.mark.parametrize("rule_type, found, matches, expected", [
    ("must_exist", True, True, S.COMPLIANT),
    ("must_exist", True, False, S.NON_COMPLIANT),
    ("must_exist", False, False, S.MISSING),
    ("must_exist", False, True, S.MISSING),
    ("condition", True, True, S.COMPLIANT),
    ("condition", True, False, S.NON_COMPLIANT),
    ("condition", False, False, S.MISSING),
    ("must_not_exist", True, True, S.NON_COMPLIANT),
    ("must_not_exist", True, False, S.COMPLIANT),
    ("must_not_exist", False, False, S.COMPLIANT),
])
def test_status_table(rule_type, found, matches, expected):
    assert status_for(rule_type, found, matches) is expected


def test_status_values_are_the_spec_strings():
    assert [s.value for s in Status] == ["uyumlu", "uyumsuz", "eksik", "belirsiz", "hata"]


@pytest.mark.parametrize("rule_type, status, expected", [
    ("must_exist", S.MISSING, True),
    ("condition", S.MISSING, True),
    ("must_not_exist", S.COMPLIANT, True),
    ("must_exist", S.COMPLIANT, False),
    ("must_not_exist", S.NON_COMPLIANT, False),
    ("must_exist", S.UNCERTAIN, False),
])
def test_absence_verdict(rule_type, status, expected):
    assert is_absence_verdict(rule_type, status) is expected


def test_rule_risk():
    assert rule_risk("high", S.COMPLIANT) == 0.0
    assert rule_risk("medium", S.MISSING) == 2.0
    assert rule_risk("low", S.UNCERTAIN) == 0.5
    assert rule_risk("high", S.NON_COMPLIANT) == 3.0
    assert rule_risk("high", S.ERROR) is None


def test_risk_score_ignores_errors():
    items = [("high", S.COMPLIANT), ("medium", S.MISSING), ("low", S.UNCERTAIN), ("high", S.ERROR)]
    assert risk_score(items) == pytest.approx(41.7)


def test_risk_score_bounds():
    assert risk_score([("low", S.COMPLIANT)]) == 0.0
    assert risk_score([("low", S.NON_COMPLIANT), ("high", S.MISSING)]) == 100.0
    assert risk_score([("high", S.ERROR)]) is None
    assert risk_score([]) is None
