"""Audit benchmark on the fixed CUAD subset: audit each contract with the commercial playbook,
compare clause presence with the lawyers' marks, and record time and cost per audit.

Free (local):  python -m benchmarks.audit_bench --provider ollama --ollama-model qwen3:8b
Paid (OpenAI): python -m benchmarks.audit_bench --provider openai --eval-model gpt-5.4-mini \
                   --small-model gpt-5.4-mini --max-cost 3
Audits are cached in --data-dir/audits.db (errored ones too), so a stopped or interrupted run resumes for free.
"""

import argparse
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from statistics import mean

from dotenv import load_dotenv

from auditor.audit.nodes import AuditConfig
from auditor.audit.playbook import PlaybookError
from auditor.audit.runner import Auditor
from auditor.bench.budget import Budget, BudgetExceeded
from auditor.bench.cuad import CuadContract, load_cuad, load_subset
from auditor.bench.metrics import citation_hits, prf
from auditor.config import Settings
from auditor.ingestion.indexer import Indexer
from auditor.llm.base import ProviderUnavailableError, models_label
from auditor.llm.factory import PROVIDERS, cached_provider_factory
from auditor.llm.openai_provider import parse_prices
from auditor.storage.db import AuditStore
from benchmarks.retrieval_bench import index_contracts, real_stack, write_result

SUBSET_FILE = Path(__file__).parent / "subset.json"
TITLE = "Audit on the CUAD subset"

CUAD_CATEGORY_BY_RULE = {
    "liability_cap": "Cap On Liability",
    "unlimited_liability": "Uncapped Liability",
    "termination_notice": "Termination For Convenience",
    "governing_law": "Governing Law",
    "anti_assignment": "Anti-Assignment",
    "change_of_control": "Change Of Control",
    "non_compete": "Non-Compete",
    "exclusivity": "Exclusivity",
    "audit_rights": "Audit Rights",
    "insurance": "Insurance",
    "warranty_duration": "Warranty Duration",
    "ip_ownership": "Ip Ownership Assignment",
    "liquidated_damages": "Liquidated Damages",
    "minimum_commitment": "Minimum Commitment",
    "post_termination_services": "Post-Termination Services",
    "third_party_beneficiary": "Third Party Beneficiary",
    "renewal_term": "Renewal Term",
}


@dataclass
class AuditStack:
    indexer: Indexer
    auditor: Auditor


@dataclass
class AuditTally:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    findings: int = 0
    undecided: int = 0
    errors: int = 0
    citations: int = 0
    citation_hits: int = 0
    seconds: list[float] = field(default_factory=list)
    costs: list[float] = field(default_factory=list)


def presence(rule_type: str, status: str) -> bool | None:
    """Whether the audit says the clause is in the contract; None when it could not decide."""
    if status in ("belirsiz", "hata"):
        return None
    if rule_type == "must_not_exist":
        return status == "uyumsuz"
    return status in ("uyumlu", "uyumsuz")


def score_report(report: dict, contract: CuadContract, mapping: dict[str, str], tally: AuditTally) -> None:
    tally.seconds.append(report["totals"]["duration_s"])
    tally.costs.append(report["totals"]["cost_usd"])
    for finding in report["findings"]:
        category = mapping.get(finding["rule_id"])
        if category is None:
            continue
        tally.findings += 1
        if finding["status"] == "hata":
            tally.errors += 1
        predicted = presence(finding["type"], finding["status"])
        gold = contract.spans.get(category, [])
        if predicted is None:
            tally.undecided += 1
            continue
        if not predicted and not gold:
            tally.tp += 1
        elif not predicted:
            tally.fp += 1
        elif not gold:
            tally.fn += 1
        else:
            spans = [(c["char_start"], c["char_end"]) for c in finding["citations"]]
            tally.citations += len(spans)
            tally.citation_hits += citation_hits(spans, gold)


def audit_row(provider: str, models: str, tally: AuditTally, contracts: int, rules: int) -> dict:
    result = prf(tally.tp, tally.fp, tally.fn)
    return {
        "provider": provider,
        "models": models,
        "contracts": contracts,
        "rules": rules,
        "missing precision": round(result.precision, 3),
        "missing recall": round(result.recall, 3),
        "missing F1": round(result.f1, 3),
        "citation accuracy": round(tally.citation_hits / tally.citations, 3) if tally.citations else None,
        "undecided %": round(100 * tally.undecided / tally.findings, 1) if tally.findings else None,
        "errors": tally.errors,
        "seconds per audit": round(mean(tally.seconds), 1) if tally.seconds else None,
        "USD per audit": round(mean(tally.costs), 4) if tally.costs else None,
    }


def real_audit_stack(settings: Settings, data_dir: Path, provider_factory, concurrency: int) -> AuditStack:
    stack = real_stack(settings, "structural", data_dir / "structural")
    auditor = Auditor(stack.retriever, stack.indexer._docstore, AuditStore(data_dir / "audits.db"),
                      settings.playbooks_dir, provider_factory, AuditConfig(concurrency=concurrency))
    return AuditStack(stack.indexer, auditor)


def _provider_settings(settings: Settings, args: argparse.Namespace) -> Settings:
    if args.provider == "openai":
        return replace(settings, openai_eval_model=args.eval_model or settings.openai_eval_model,
                       openai_small_model=args.small_model or settings.openai_small_model)
    return replace(settings, ollama_model=args.ollama_model or settings.ollama_model)


def _non_negative(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return value


def main(argv: list[str] | None = None, stack_factory=None, provider_factory=None,
         mapping: dict[str, str] = CUAD_CATEGORY_BY_RULE) -> int:
    parser = argparse.ArgumentParser(prog="audit_bench")
    parser.add_argument("--cuad", default="data/cuad/CUAD_v1.json")
    parser.add_argument("--subset", default=str(SUBSET_FILE))
    parser.add_argument("--contracts", type=_non_negative, default=0, help="first N subset contracts only")
    parser.add_argument("--provider", choices=PROVIDERS, required=True)
    parser.add_argument("--eval-model")
    parser.add_argument("--small-model")
    parser.add_argument("--ollama-model")
    parser.add_argument("--playbook", default="commercial_contract")
    parser.add_argument("--max-cost", type=float, default=3.0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--data-dir", default="data/bench")
    parser.add_argument("--out", default="benchmarks/results")
    args = parser.parse_args(argv)

    load_dotenv()
    settings = _provider_settings(Settings.from_env(), args)
    providers = provider_factory or cached_provider_factory(settings)
    data_dir = Path(args.data_dir)
    stack = (stack_factory or real_audit_stack)(settings, data_dir, providers, args.concurrency)

    contracts_by_title = {c.title: c for c in load_cuad(args.cuad)[0]}
    contracts = [contracts_by_title[title] for title in load_subset(args.subset)]
    subset_size = len(contracts)
    if args.contracts:
        contracts = contracts[:args.contracts]
    partial = len(contracts) < subset_size
    if not contracts:
        print("error: no contracts to audit")
        return 1
    ids = index_contracts(contracts, stack.indexer)

    tally, budget, done, stopped, models, rules = AuditTally(), Budget(args.max_cost), 0, None, "-", 0
    for n, contract in enumerate(contracts):
        try:
            prepared = stack.auditor.prepare(ids[contract.title], args.playbook, args.provider)
        except (ProviderUnavailableError, PlaybookError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
        models = models_label(prepared.provider)
        if n == 0 and prepared.provider.name == "openai":
            used = {prepared.provider.model_for("eval"), prepared.provider.model_for("small")}
            missing = sorted(used - set(parse_prices(settings.openai_prices)))
            if missing:
                print(f"error: no price for {', '.join(missing)} in OPENAI_PRICES; the budget cap would not work")
                return 1
        rules = sum(1 for rule in prepared.playbook.playbook.rules if rule.id in mapping)
        report = stack.auditor.cached(prepared) or stack.auditor.latest(prepared)
        if report is None:
            try:
                budget.check(remaining=len(contracts) - n)
            except BudgetExceeded as exc:
                stopped = str(exc)
                break
            report = stack.auditor.execute(prepared)
            budget.record(report["totals"]["cost_usd"])
        score_report(report, contract, mapping, tally)
        done += 1
        print(f"  {done}/{len(contracts)} {contract.title[:60]}  {report['totals']['duration_s']} s  "
              f"${report['totals']['cost_usd']:.4f}{'  (cached)' if report.get('cached') else ''}")

    provider_name = prepared.provider.name
    slug = re.sub(r"[^a-z0-9]+", "-", f"{provider_name}-{models}".lower()).strip("-")
    if partial:
        slug += f"-first{len(contracts)}"
    scope = (f"{done} of the first {len(contracts)} of {subset_size} subset contracts" if partial
             else f"{done} of {len(contracts)} subset contracts")
    notes = (f"{scope}; positive class: clause missing; "
             f"citation accuracy counts quotes overlapping a marked span; "
             f"undecided % includes errors.")
    if stopped:
        notes += f" stopped by budget: {stopped}"
        print(f"stopped by budget: {stopped}")
    write_result(Path(args.out), f"audit-{slug}", TITLE,
                 [audit_row(provider_name, models, tally, done, rules)], notes)
    return 2 if stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
