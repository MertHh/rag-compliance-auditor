from pathlib import Path

from auditor.audit.playbook import load_playbook

ROOT = Path(__file__).parents[1]


def test_commercial_playbook():
    loaded = load_playbook(ROOT / "playbooks" / "commercial_contract.yaml")
    rules = loaded.playbook.rules
    assert len(rules) == 18
    assert {r.type for r in rules} == {"must_exist", "must_not_exist", "condition"}
    assert {"liability_cap", "termination_notice", "governing_law", "confidentiality",
            "unlimited_liability"} <= {r.id for r in rules}
    assert all(len(r.queries) >= 2 for r in rules)


def test_gdpr_playbook():
    loaded = load_playbook(ROOT / "playbooks" / "gdpr_dpa.yaml")
    rules = loaded.playbook.rules
    assert len(rules) == 12
    assert {r.type for r in rules} == {"must_exist", "must_not_exist", "condition"}
    assert all("Art." in r.criteria or "Chapter V" in r.criteria for r in rules)
