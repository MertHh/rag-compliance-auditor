"""Retrieval benchmark on CUAD. For every contract and clause category the lawyers marked,
search that contract alone and record the rank of the first chunk overlapping a marked
span. The best rerank score of every (contract, category) pair, marked or not, measures
clause presence from retrieval alone and picks min_rerank_score.

Free:            python -m benchmarks.retrieval_bench --part modes --part chunking
Context prefix:  python -m benchmarks.retrieval_bench --part prefix --provider ollama
Index, ranks and scores are saved under --data-dir, so an interrupted run resumes.
"""

import argparse
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cache, partial
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from auditor.bench.budget import Budget, BudgetExceeded
from auditor.bench.cuad import CuadContract, clause_categories, load_cuad, load_subset, query_for
from auditor.bench.metrics import (
    absence_prf,
    best_f1_threshold,
    first_hit,
    mrr,
    recall_at,
    threshold_for_present_recall,
)
from auditor.benchmark_results import BenchmarkFile
from auditor.config import Settings
from auditor.index.qdrant_store import QdrantStore
from auditor.index.store import SearchFilter
from auditor.ingestion.context import LLMContextualizer
from auditor.ingestion.indexer import IngestResult, Indexer
from auditor.ingestion.parser import parse_text
from auditor.ingestion.semantic import build_semantic_chunks
from auditor.llm.base import LLMProvider, ProviderUnavailableError, models_label
from auditor.llm.factory import PROVIDERS, build_provider
from auditor.retrieval.config import RetrievalConfig
from auditor.retrieval.pipeline import Retriever
from auditor.storage.docstore import DocumentStore

MODES = {
    "bm25": RetrievalConfig(mode="bm25", rerank=False, final_k=30),
    "dense": RetrievalConfig(mode="dense", rerank=False, final_k=30),
    "hybrid": RetrievalConfig(mode="hybrid", rerank=False, final_k=30),
    "hybrid + rerank": RetrievalConfig(mode="hybrid", rerank=True, final_k=30),
}
RERANKED = "hybrid + rerank"
SUBSET_FILE = Path(__file__).parent / "subset.json"
SAVE_EVERY = 200


@dataclass
class Stack:
    indexer: Indexer
    retriever: Retriever


@cache
def _models(embed_model: str, rerank_model: str, device: str | None):
    from auditor.index.embedder import BgeM3Embedder, Bm25SparseEncoder
    from auditor.retrieval.reranker import BgeReranker

    return BgeM3Embedder(embed_model, device), Bm25SparseEncoder(), BgeReranker(rerank_model, device)


def real_stack(settings: Settings, variant: str, directory: Path, contextualizer=None) -> Stack:
    from qdrant_client import QdrantClient

    embedder, sparse, reranker = _models(settings.embed_model, settings.rerank_model, settings.device)
    directory.mkdir(parents=True, exist_ok=True)
    store = QdrantStore(QdrantClient(path=str(directory / "qdrant")), "chunks")
    docstore = DocumentStore(directory / "documents")
    chunker = partial(build_semantic_chunks, embedder=embedder) if variant == "semantic" else None
    lock = threading.Lock()
    return Stack(
        Indexer(store, embedder, sparse, docstore, lock=lock, chunker=chunker, contextualizer=contextualizer),
        Retriever(store, embedder, sparse, reranker, docstore, lock),
    )


def index_contracts(contracts: list[CuadContract], indexer: Indexer,
                    on_indexed: Callable[[IngestResult, int], None] | None = None,
                    log: Callable[[str], None] = print) -> dict[str, str]:
    ids: dict[str, str] = {}
    started = time.perf_counter()
    for n, contract in enumerate(contracts, start=1):
        filename = f"{contract.title}.txt"
        if parse_text(contract.text, filename).text != contract.text:
            raise ValueError(f"{contract.title}: indexed text differs from the CUAD text; "
                             "spans would not line up")
        result = indexer.ingest_text(contract.text, filename)
        ids[contract.title] = result.document_id
        if on_indexed is not None:
            on_indexed(result, len(contracts) - n)
        if n % 25 == 0 or n == len(contracts):
            log(f"  indexed {n}/{len(contracts)} ({time.perf_counter() - started:.0f} s)")
    return ids


def _save(path: Path | None, state: dict) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")


def evaluate(contracts: list[CuadContract], ids: dict[str, str], retriever: Retriever,
             details: dict[str, str], modes: list[str], cache_path: Path | None,
             log: Callable[[str], None] = print) -> dict:
    state = (json.loads(cache_path.read_text(encoding="utf-8"))
             if cache_path is not None and cache_path.exists() else {"ranks": {}, "top": {}})
    for mode in modes:
        state["ranks"].setdefault(mode, {})
    categories = clause_categories(details)
    total, searched, started = len(contracts) * len(categories), 0, time.perf_counter()
    for n, (contract, category) in enumerate(((c, cat) for c in contracts for cat in categories), 1):
        key = f"{contract.title}__{category}"
        gold = contract.spans.get(category, [])
        flt = SearchFilter(document_ids=[ids[contract.title]])
        query = query_for(category, details)
        for mode in modes:
            needs_rank = bool(gold) and key not in state["ranks"][mode]
            needs_top = mode == RERANKED and key not in state["top"]
            if not (needs_rank or needs_top):
                continue
            result = retriever.search(query, MODES[mode], flt)
            searched += 1
            if gold:
                spans = [(chunk.char_start, chunk.char_end) for chunk in result.chunks]
                state["ranks"][mode][key] = first_hit(spans, gold)
            if mode == RERANKED:
                state["top"][key] = result.chunks[0].scores.rerank_score if result.chunks else 0.0
            if searched % SAVE_EVERY == 0:
                _save(cache_path, state)
        if n % 1000 == 0:
            log(f"  pairs {n}/{total} ({time.perf_counter() - started:.0f} s)")
    _save(cache_path, state)
    return state


def _positive_keys(contracts: list[CuadContract], details: dict[str, str]) -> list[str]:
    return [f"{c.title}__{cat}" for c in contracts for cat in clause_categories(details) if c.spans.get(cat)]


def _rank_row(label: str, ranks: list[int | None], **extra) -> dict:
    return {"config": label, **extra, "recall@5": round(recall_at(ranks, 5), 3),
            "recall@30": round(recall_at(ranks, 30), 3), "MRR": round(mrr(ranks), 3),
            "queries": len(ranks)}


def write_result(out_dir: Path, name: str, title: str, rows: list[dict], notes: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    data = BenchmarkFile(title=title, created_at=datetime.now(timezone.utc).date().isoformat(),
                         rows=rows, notes=notes)
    (out_dir / f"{name}.json").write_text(json.dumps(data.model_dump(), indent=2) + "\n",
                                          encoding="utf-8")


def _evaluated(variant: str, contracts, details, modes, factory, data_dir: Path, log,
               contextualizer=None, on_indexed=None) -> dict:
    stack = (factory(variant, data_dir / variant, contextualizer) if contextualizer is not None
             else factory(variant, data_dir / variant))
    ids = index_contracts(contracts, stack.indexer, on_indexed, log)
    return evaluate(contracts, ids, stack.retriever, details, modes, data_dir / variant / "ranks.json", log)


def run_modes(contracts, details, factory, data_dir: Path, out_dir: Path, log) -> None:
    log(f"modes: {len(contracts)} contracts")
    state = _evaluated("structural", contracts, details, list(MODES), factory, data_dir, log)
    keys = _positive_keys(contracts, details)
    rows = [_rank_row(mode, [state["ranks"][mode][k] for k in keys]) for mode in MODES]
    write_result(out_dir, "retrieval", f"Retrieval on CUAD ({len(contracts)} contracts)", rows,
                 "Each query searches one contract; a hit is the first chunk overlapping a span the "
                 "lawyers marked. Structural chunking, no context prefix.")
    pairs = [(state["top"][f"{c.title}__{cat}"], bool(c.spans.get(cat)))
             for c in contracts for cat in clause_categories(details)]
    current = RetrievalConfig().min_rerank_score
    best, _ = best_f1_threshold(pairs)
    safe = threshold_for_present_recall(pairs, 0.95)
    rows = []
    for label, threshold in (("provisional default", current), ("best F1", best),
                             ("keeps 95% of present clauses", safe)):
        result = absence_prf(pairs, threshold)
        rows.append({"threshold rule": label, "threshold": round(threshold, 4),
                     "missing precision": round(result.precision, 3),
                     "missing recall": round(result.recall, 3), "missing F1": round(result.f1, 3)})
    write_result(out_dir, "presence", "Clause presence from retrieval alone (hybrid + rerank)", rows,
                 f"Positive class: clause missing. {len(pairs)} contract-category pairs. "
                 f"Recommended min_rerank_score: {safe:.4f} (keeps 95% of present clauses above it).")


def run_chunking(contracts, details, factory, data_dir: Path, out_dir: Path, log) -> None:
    log(f"chunking: {len(contracts)} contracts")
    keys = _positive_keys(contracts, details)
    rows = []
    for variant in ("structural", "semantic"):
        state = _evaluated(variant, contracts, details, [RERANKED], factory, data_dir, log)
        rows.append(_rank_row(variant, [state["ranks"][RERANKED][k] for k in keys]))
    write_result(out_dir, "chunking", "Chunking (hybrid + rerank)", rows,
                 "Semantic chunks break where adjacent sentence embeddings drift furthest "
                 "(90th percentile), at most 400 tokens; structural chunks follow clause numbering.")


def run_prefix(contracts, details, factory, data_dir: Path, out_dir: Path, provider: LLMProvider,
               max_cost: float, log) -> None:
    log(f"context prefix: {len(contracts)} subset contracts with {models_label(provider)}")
    keys = _positive_keys(contracts, details)
    off = _evaluated("structural", contracts, details, [RERANKED], factory, data_dir, log)
    contextualizer = LLMContextualizer(lambda: provider)
    budget, seen = Budget(max_cost), [0.0]

    def guard(result: IngestResult, remaining: int) -> None:
        if result.already_indexed:
            return
        budget.record(contextualizer.usage.cost_usd - seen[0])
        seen[0] = contextualizer.usage.cost_usd
        budget.check(remaining)

    on = _evaluated("prefix", contracts, details, [RERANKED], factory, data_dir, log,
                    contextualizer=contextualizer, on_indexed=guard)
    label = f"{provider.name} {models_label(provider)}"
    rows = [_rank_row("off", [off["ranks"][RERANKED][k] for k in keys], **{"context model": "-"}),
            _rank_row("on", [on["ranks"][RERANKED][k] for k in keys], **{"context model": label})]
    write_result(out_dir, "context_prefix", f"Context prefix ({len(contracts)}-contract subset, hybrid + rerank)",
                 rows, f"One LLM sentence per chunk, prepended before embedding. Cost "
                       f"${contextualizer.usage.cost_usd:.2f}; {contextualizer.failures} chunks without a prefix.")


def main(argv: list[str] | None = None, stack_factory=None, provider_factory=None) -> int:
    parser = argparse.ArgumentParser(prog="retrieval_bench")
    parser.add_argument("--cuad", default="data/cuad/CUAD_v1.json")
    parser.add_argument("--part", action="append", choices=["modes", "chunking", "prefix"])
    parser.add_argument("--contracts", type=int, default=0, help="first N contracts only (quick runs)")
    parser.add_argument("--subset", default=str(SUBSET_FILE))
    parser.add_argument("--data-dir", default="data/bench")
    parser.add_argument("--out", default="benchmarks/results")
    parser.add_argument("--provider", choices=PROVIDERS, default="ollama", help="context prefix model")
    parser.add_argument("--max-cost", type=float, default=3.0)
    args = parser.parse_args(argv)
    parts = args.part or ["modes", "chunking"]

    load_dotenv()
    settings = Settings.from_env()
    factory = stack_factory or (lambda variant, directory, contextualizer=None:
                                real_stack(settings, variant, directory, contextualizer))
    contracts, details = load_cuad(args.cuad)
    contracts = sorted(contracts, key=lambda c: c.title)
    if args.contracts:
        contracts = contracts[:args.contracts]
    data_dir, out_dir = Path(args.data_dir), Path(args.out)
    if "modes" in parts:
        run_modes(contracts, details, factory, data_dir, out_dir, print)
    if "chunking" in parts:
        run_chunking(contracts, details, factory, data_dir, out_dir, print)
    if "prefix" in parts:
        wanted = set(load_subset(args.subset))
        subset = [c for c in contracts if c.title in wanted]
        if not subset:
            print("error: no subset contracts among the selected contracts")
            return 1
        provider = (provider_factory or (lambda name: build_provider(name, settings)))(args.provider)
        try:
            provider.check_available()
            run_prefix(subset, details, factory, data_dir, out_dir, provider, args.max_cost, print)
        except ProviderUnavailableError as exc:
            print(f"error: {exc}")
            return 1
        except BudgetExceeded as exc:
            print(f"stopped by budget: {exc}")
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
