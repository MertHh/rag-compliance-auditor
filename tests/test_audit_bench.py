import json

import pytest
from cuad_fixture import CAP, LAW, write_cuad
from fakes import FakeLLM
from test_retrieval_bench import fake_stack

import benchmarks.audit_bench as bench
from auditor.audit.nodes import AuditConfig
from auditor.audit.playbook import load_playbook
from auditor.audit.prompts import Evaluation, Relevance, RewrittenQueries
from auditor.audit.runner import Auditor
from auditor.bench.cuad import CUAD_CATEGORIES, save_subset
from auditor.llm.base import LLMResult, Usage
from auditor.storage.db import AuditStore

PLAYBOOK = """name: Bench test
rules:
  - id: liability_cap
    title: Liability cap
    type: must_exist
    severity: high
    queries: ["total liability fees paid"]
    criteria: "Liability is capped."
  - id: governing_law
    title: Governing law
    type: must_exist
    severity: low
    queries: ["governed by the laws of the State"]
    criteria: "A governing law is named."
"""
MAPPING = {"liability_cap": "Cap On Liability", "governing_law": "Governing Law"}


def evaluation(user):
    for title, needle in (("Liability cap", CAP), ("Governing law", LAW)):
        if f"Rule: {title}\n" in user:
            if needle in user:
                return Evaluation(clause_found=True, matches_criteria=True, reasoning="found", quotes=[needle])
            return Evaluation(clause_found=False, matches_criteria=False, reasoning="absent", quotes=[])
    raise AssertionError(user[:80])


class PricedLLM(FakeLLM):
    def __init__(self, cost):
        super().__init__({"Evaluation": evaluation, "Relevance": Relevance(relevant=False),
                          "RewrittenQueries": RewrittenQueries(queries=["other wording"])})
        self.cost = cost

    def complete(self, system, user, schema, tier):
        result = super().complete(system, user, schema, tier)
        return LLMResult(result.value, result.model, Usage(100, 20, self.cost))


@pytest.fixture
def setup(tmp_path):
    playbooks = tmp_path / "playbooks"
    playbooks.mkdir()
    (playbooks / "bench_pb.yaml").write_text(PLAYBOOK, encoding="utf-8")
    subset = tmp_path / "subset.json"
    save_subset(subset, ["ALPHA-SUPPLY", "BETA-SERVICES", "GAMMA-LICENSE"])
    return {"cuad": write_cuad(tmp_path / "cuad.json"), "data": tmp_path / "bench",
            "out": tmp_path / "results", "subset": subset, "playbooks": playbooks}


def _stack_factory(setup):
    def factory(settings, data_dir, provider_factory, concurrency):
        stack = fake_stack("structural", data_dir / "structural")
        auditor = Auditor(stack.retriever, stack.indexer._docstore, AuditStore(data_dir / "audits.db"),
                          setup["playbooks"], provider_factory, AuditConfig(concurrency=concurrency))
        return bench.AuditStack(stack.indexer, auditor)
    return factory


def _run(setup, llm, *extra):
    argv = ["--cuad", str(setup["cuad"]), "--subset", str(setup["subset"]), "--data-dir", str(setup["data"]),
            "--out", str(setup["out"]), "--provider", "openai", "--playbook", "bench_pb", *extra]
    return bench.main(argv, stack_factory=_stack_factory(setup), provider_factory=lambda name: llm,
                      mapping=MAPPING)


def _row(setup):
    [path] = list(setup["out"].glob("audit-*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    return path.name, data


def test_perfect_fake_audits_score_one(setup):
    assert _run(setup, PricedLLM(0.0)) == 0
    name, data = _row(setup)
    assert name == "audit-fake-fake-eval-fake-small.json"
    assert data["title"] == "Audit on the CUAD subset"
    [row] = data["rows"]
    assert (row["contracts"], row["rules"]) == (3, 2)
    assert (row["missing precision"], row["missing recall"], row["missing F1"]) == (1.0, 1.0, 1.0)
    assert row["citation accuracy"] == 1.0
    assert row["undecided %"] == 0.0 and row["errors"] == 0


def test_budget_stops_then_rerun_resumes_without_paying_twice(setup, capsys):
    assert _run(setup, PricedLLM(0.01), "--max-cost", "0.05") == 2
    _, data = _row(setup)
    assert data["rows"][0]["contracts"] == 1
    assert "stopped by budget" in data["notes"]
    assert "stopped by budget" in capsys.readouterr().out

    assert _run(setup, PricedLLM(0.01), "--max-cost", "100") == 0
    _, data = _row(setup)
    assert data["rows"][0]["contracts"] == 3
    assert len(AuditStore(setup["data"] / "audits.db").list_audits()) == 3


def test_presence_mapping():
    assert bench.presence("must_exist", "uyumlu") is True
    assert bench.presence("condition", "uyumsuz") is True
    assert bench.presence("must_exist", "eksik") is False
    assert bench.presence("must_not_exist", "uyumsuz") is True
    assert bench.presence("must_not_exist", "uyumlu") is False
    assert bench.presence("must_exist", "belirsiz") is None
    assert bench.presence("must_exist", "hata") is None


def test_mapping_covers_the_shipped_playbook():
    from pathlib import Path

    rules = load_playbook(Path(__file__).parents[1] / "playbooks" / "commercial_contract.yaml").playbook.rules
    ids = {rule.id for rule in rules}
    assert set(bench.CUAD_CATEGORY_BY_RULE) == ids - {"confidentiality"}
    assert set(bench.CUAD_CATEGORY_BY_RULE.values()) <= set(CUAD_CATEGORIES)


def test_openai_without_prices_is_refused_before_any_audit(setup, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_PRICES", "")
    llm = PricedLLM(0.01)
    llm.name = "openai"
    assert _run(setup, llm) == 1
    assert "no price for fake-eval, fake-small in OPENAI_PRICES" in capsys.readouterr().out
    assert AuditStore(setup["data"] / "audits.db").list_audits() == []


def test_empty_subset_is_an_error(setup, capsys):
    save_subset(setup["subset"], [])
    assert _run(setup, PricedLLM(0.0)) == 1
    assert "no contracts to audit" in capsys.readouterr().out


def test_negative_contract_count_is_rejected(setup):
    with pytest.raises(SystemExit):
        _run(setup, PricedLLM(0.0), "--contracts", "-1")


def test_resume_does_not_rerun_audits_with_errors(setup):
    class Flaky(PricedLLM):
        def complete(self, system, user, schema, tier):
            if schema.__name__ == "Evaluation" and "Rule: Governing law\n" in user:
                raise RuntimeError("boom")
            return super().complete(system, user, schema, tier)

    assert _run(setup, Flaky(0.0)) == 0
    _, data = _row(setup)
    assert data["rows"][0]["errors"] == 3
    assert len(AuditStore(setup["data"] / "audits.db").list_audits()) == 3
    assert _run(setup, Flaky(0.0)) == 0
    assert len(AuditStore(setup["data"] / "audits.db").list_audits()) == 3


def test_partial_run_names_its_file_and_note_after_the_first_contracts(setup):
    # A quick --contracts run must not overwrite the full-subset file or read as the full subset.
    assert _run(setup, PricedLLM(0.0)) == 0
    assert _run(setup, PricedLLM(0.0), "--contracts", "2") == 0
    names = sorted(p.name for p in setup["out"].glob("audit-*.json"))
    assert names == ["audit-fake-fake-eval-fake-small-first2.json", "audit-fake-fake-eval-fake-small.json"]
    partial = json.loads((setup["out"] / names[0]).read_text(encoding="utf-8"))
    assert partial["rows"][0]["contracts"] == 2
    assert partial["notes"].startswith("2 of the first 2 of 3 subset contracts;")
    full = json.loads((setup["out"] / names[1]).read_text(encoding="utf-8"))
    assert full["notes"].startswith("3 of 3 subset contracts;")
