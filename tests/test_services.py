from dataclasses import replace

import auditor.index.embedder as embedder_module
import auditor.retrieval.reranker as reranker_module
from auditor.config import Settings
from auditor.services import build_services


def test_models_load_on_warm_up_not_on_build(tmp_path, monkeypatch):
    built = []

    def stub(name, **attrs):
        def init(self, *args, **kwargs):
            built.append(name)
        return type(name, (), {"__init__": init, **attrs})

    monkeypatch.setattr(embedder_module, "BgeM3Embedder", stub("BgeM3Embedder", dim=64))
    monkeypatch.setattr(embedder_module, "Bm25SparseEncoder", stub("Bm25SparseEncoder"))
    monkeypatch.setattr(reranker_module, "BgeReranker", stub("BgeReranker"))
    settings = replace(Settings.from_env(), data_dir=tmp_path, qdrant_url=None,
                       playbooks_dir=tmp_path / "pb", benchmarks_dir=tmp_path / "bench")

    services = build_services(settings)
    try:
        assert built == []
        assert services.retriever._lock is services.indexer._lock
        assert services.playbooks_dir == tmp_path / "pb"
        assert services.benchmarks_dir == tmp_path / "bench"
        services.warm_up()
        assert sorted(built) == ["BgeM3Embedder", "BgeReranker", "Bm25SparseEncoder"]
        services.warm_up()
        assert len(built) == 3
    finally:
        services.store._client.close()


def test_context_prefix_wires_a_contextualizer(tmp_path, monkeypatch):
    from auditor.ingestion.context import LLMContextualizer

    for module, name in [(embedder_module, "BgeM3Embedder"), (embedder_module, "Bm25SparseEncoder"),
                         (reranker_module, "BgeReranker")]:
        monkeypatch.setattr(module, name, type(name, (), {"__init__": lambda self, *a, **k: None}))
    base = replace(Settings.from_env(), data_dir=tmp_path, qdrant_url=None)
    off = build_services(replace(base, context_prefix=False))
    off.store._client.close()
    on = build_services(replace(base, data_dir=tmp_path / "on", context_prefix=True))
    on.store._client.close()
    assert off.indexer._contextualizer is None
    assert isinstance(on.indexer._contextualizer, LLMContextualizer)
