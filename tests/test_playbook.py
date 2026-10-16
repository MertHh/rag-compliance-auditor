import pytest

from auditor.audit.playbook import (
    PlaybookError,
    PlaybookNotFound,
    find_playbook,
    list_playbooks,
    load_playbook,
)

VALID = """name: Test playbook
rules:
  - id: liability_cap
    title: Liability cap
    type: must_exist
    severity: high
    queries: ["limitation of liability"]
    criteria: "Total liability is capped."
"""


def _write(tmp_path, text, name="pb.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _error(path) -> str:
    with pytest.raises(PlaybookError) as exc:
        load_playbook(path)
    return str(exc.value)


def test_load_valid(tmp_path):
    loaded = load_playbook(_write(tmp_path, VALID))
    assert loaded.key == "pb"
    assert loaded.playbook.name == "Test playbook"
    rule = loaded.playbook.rules[0]
    assert (rule.id, rule.type, rule.severity) == ("liability_cap", "must_exist", "high")
    assert rule.queries == ["limitation of liability"]
    assert len(loaded.sha256) == 64


def test_line_endings_do_not_change_the_fingerprint(tmp_path):
    variants = {
        "lf": VALID,
        "crlf": VALID.replace("\n", "\r\n"),
        "mixed": VALID.replace("\n", "\r\n", 3),
    }
    shas = set()
    for name, text in variants.items():
        path = tmp_path / f"{name}.yaml"
        path.write_bytes(text.encode("utf-8"))
        shas.add(load_playbook(path).sha256)
    changed = tmp_path / "changed.yaml"
    changed.write_bytes(VALID.replace("high", "low").encode("utf-8"))
    assert len(shas) == 1
    assert load_playbook(changed).sha256 not in shas


def test_error_names_rule_and_field(tmp_path):
    message = _error(_write(tmp_path, VALID.replace("severity: high", "severity: critical")))
    assert "rule 'liability_cap' (rules[0])" in message
    assert "'severity'" in message
    assert message.startswith("pb.yaml:")


def test_missing_field(tmp_path):
    text = VALID.replace('    criteria: "Total liability is capped."\n', "")
    message = _error(_write(tmp_path, text))
    assert "'criteria'" in message
    assert "Field required" in message


def test_blank_query_is_rejected(tmp_path):
    message = _error(_write(tmp_path, VALID.replace('["limitation of liability"]', '["  "]')))
    assert "'queries'" in message


def test_duplicate_rule_ids(tmp_path):
    rules = VALID.split("rules:\n")[1]
    assert "duplicate rule id 'liability_cap'" in _error(_write(tmp_path, VALID + rules))


def test_invalid_yaml(tmp_path):
    assert "invalid YAML" in _error(_write(tmp_path, "name: [unclosed"))


def test_not_a_mapping(tmp_path):
    assert "mapping" in _error(_write(tmp_path, "- just a list"))


def test_find_and_list(tmp_path):
    _write(tmp_path, VALID, "b.yaml")
    _write(tmp_path, VALID, "a.yaml")
    _write(tmp_path, "notes", "notes.txt")
    assert list_playbooks(tmp_path) == ["a", "b"]
    assert find_playbook(tmp_path, "a").key == "a"
    with pytest.raises(PlaybookNotFound, match="available: a, b"):
        find_playbook(tmp_path, "missing")
    with pytest.raises(PlaybookNotFound):
        find_playbook(tmp_path, "../a")

