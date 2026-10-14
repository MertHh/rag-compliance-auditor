import json
import threading

import pytest
from cuad_fixture import write_cuad
from fakes import FakeEmbedder, FakeLLM, FakeReranker, FakeSparseEncoder

import benchmarks.retrieval_bench as bench
from auditor.bench.cuad import CuadContract, save_subset
from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.context import ContextLine
from auditor.ingestion.indexer import Indexer
from auditor.ingestion.semantic import build_semantic_chunks
from auditor.llm.base import LLMResult, Usage
from auditor.retrieval.pipeline import Retriever
from auditor.storage.docstore import DocumentStore


def fake_stack(variant, directory, contextualizer=None):
    store, docstore = QdrantStore.in_memory(), DocumentStore(directory / "documents")
    embedder, sparse, lock = FakeEmbedder(), FakeSparseEncoder(), threading.Lock()
    chunker = ((lambda doc: build_semantic_chunks(doc, embedder, breakpoint_percentile=100))
               if variant == "semantic" else None)
    return bench.Stack(
        Indexer(store, embedder, sparse, docstore, lock=lock, chunker=chunker, contextualizer=contextualizer),
        Retriever(store, embedder, sparse, FakeReranker(), docstore, lock),
    )


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def paths(tmp_path):
    return {"cuad": write_cuad(tmp_path / "cuad.json"), "data": tmp_path / "bench",
            "out": tmp_path / "results", "subset": tmp_path / "subset.json"}


def _args(paths, *parts, extra=()):
    argv = ["--cuad", str(paths["cuad"]), "--data-dir", str(paths["data"]), "--out", str(paths["out"]),
            "--subset", str(paths["subset"])]
    for part in parts:
        argv += ["--part", part]
    return argv + list(extra)


def test_modes_write_retrieval_and_presence(paths):
    assert bench.main(_args(paths, "modes"), stack_factory=fake_stack) == 0
    retrieval = _read(paths["out"] / "retrieval.json")
    assert [row["config"] for row in retrieval["rows"]] == list(bench.MODES)
    assert all(row["queries"] == 4 for row in retrieval["rows"])
    assert all(row["recall@30"] == 1.0 for row in retrieval["rows"])
    presence = _read(paths["out"] / "presence.json")
    assert [row["threshold rule"] for row in presence["rows"]] == [
        "provisional default", "best F1", "keeps 95% of present clauses"]
    assert "Recommended min_rerank_score" in presence["notes"]
    assert "6 contract-category pairs" in presence["notes"]


def test_rerun_resumes_from_saved_ranks(paths):
    bench.main(_args(paths, "modes"), stack_factory=fake_stack)

    def no_search_stack(variant, directory, contextualizer=None):
        stack = fake_stack(variant, directory, contextualizer)
        stack.retriever.search = lambda *a, **k: (_ for _ in ()).throw(AssertionError("searched again"))
        return stack

    assert bench.main(_args(paths, "modes"), stack_factory=no_search_stack) == 0


def test_chunking_compares_structural_and_semantic(paths):
    assert bench.main(_args(paths, "chunking"), stack_factory=fake_stack) == 0
    rows = _read(paths["out"] / "chunking.json")["rows"]
    assert [row["config"] for row in rows] == ["structural", "semantic"]


def test_context_prefix_on_the_subset(paths):
    save_subset(paths["subset"], ["ALPHA-SUPPLY", "GAMMA-LICENSE"])
    llm = FakeLLM({"ContextLine": ContextLine(sentence="A contract passage.")})
    code = bench.main(_args(paths, "prefix", extra=["--provider", "ollama"]),
                      stack_factory=fake_stack, provider_factory=lambda name: llm)
    assert code == 0
    data = _read(paths["out"] / "context_prefix.json")
    assert [row["config"] for row in data["rows"]] == ["off", "on"]
    assert all(row["queries"] == 3 for row in data["rows"])
    assert llm.count("ContextLine") > 0


def test_context_prefix_stops_at_the_budget(paths, capsys):
    save_subset(paths["subset"], ["ALPHA-SUPPLY", "BETA-SERVICES", "GAMMA-LICENSE"])

    class PaidLLM(FakeLLM):
        def complete(self, system, user, schema, tier):
            result = super().complete(system, user, schema, tier)
            return LLMResult(result.value, result.model, Usage(1000, 50, 0.5))

    llm = PaidLLM({"ContextLine": ContextLine(sentence="A contract passage.")})
    code = bench.main(_args(paths, "prefix", extra=["--max-cost", "0.6"]),
                      stack_factory=fake_stack, provider_factory=lambda name: llm)
    assert code == 2
    assert "stopped by budget" in capsys.readouterr().out
    assert not (paths["out"] / "context_prefix.json").exists()


def test_misaligned_text_stops_the_run(tmp_path):
    contract = CuadContract("X", "SUPPLY AGREEMENT\r\n1. Term\r\nTwo years.", {})
    stack = fake_stack("structural", tmp_path)
    with pytest.raises(ValueError, match="spans would not line up"):
        bench.index_contracts([contract], stack.indexer, log=lambda message: None)
