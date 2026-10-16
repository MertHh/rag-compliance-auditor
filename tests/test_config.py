from pathlib import Path

from auditor.config import Settings

ENV_NAMES = (
    "AUDITOR_DATA_DIR", "QDRANT_URL", "AUDITOR_COLLECTION", "EMBED_MODEL", "RERANK_MODEL",
    "AUDITOR_DEVICE", "AUDITOR_PROVIDER", "OPENAI_EVAL_MODEL", "OPENAI_SMALL_MODEL",
    "OPENAI_PRICES", "OLLAMA_HOST", "OLLAMA_MODEL", "OLLAMA_NUM_CTX", "AUDITOR_PLAYBOOKS",
    "AUDIT_CONCURRENCY", "AUDITOR_BENCHMARKS", "AUDITOR_CONTEXT_PREFIX",
    "RERANK_DEVICE", "OLLAMA_THINK",
)


def test_defaults(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    s = Settings.from_env()
    assert s.data_dir == Path("data")
    assert s.qdrant_url is None
    assert s.collection == "chunks"
    assert s.embed_model == "BAAI/bge-m3"
    assert s.rerank_model == "BAAI/bge-reranker-v2-m3"
    assert s.device is None
    assert s.provider == "openai"
    assert s.openai_eval_model is None
    assert s.openai_small_model is None
    assert s.openai_prices == ""
    assert s.ollama_host == "http://localhost:11434"
    assert s.ollama_model == "qwen3:8b"
    assert s.ollama_num_ctx == 16384
    assert s.playbooks_dir == Path("playbooks")
    assert s.audit_concurrency == 4
    assert s.benchmarks_dir == Path("benchmarks/results")
    assert s.db_path == Path("data") / "auditor.db"
    assert s.context_prefix is False
    assert s.rerank_device is None
    assert s.ollama_think is None


def test_ollama_think_and_rerank_device(monkeypatch):
    monkeypatch.setenv("OLLAMA_THINK", "0")
    monkeypatch.setenv("RERANK_DEVICE", "cpu")
    s = Settings.from_env()
    assert s.ollama_think is False and s.rerank_device == "cpu"
    monkeypatch.setenv("OLLAMA_THINK", "true")
    assert Settings.from_env().ollama_think is True


def test_context_prefix_flag(monkeypatch):
    for value, expected in [("1", True), ("true", True), ("ON", True), ("0", False), ("no", False)]:
        monkeypatch.setenv("AUDITOR_CONTEXT_PREFIX", value)
        assert Settings.from_env().context_prefix is expected


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("AUDITOR_DATA_DIR", "D:/x")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("AUDITOR_DEVICE", "cpu")
    monkeypatch.setenv("AUDITOR_PROVIDER", "ollama")
    monkeypatch.setenv("OPENAI_EVAL_MODEL", "gpt-5.5")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    monkeypatch.setenv("AUDIT_CONCURRENCY", "2")
    s = Settings.from_env()
    assert s.data_dir == Path("D:/x")
    assert s.qdrant_url == "http://localhost:6333"
    assert s.device == "cpu"
    assert s.provider == "ollama"
    assert s.openai_eval_model == "gpt-5.5"
    assert s.ollama_model == "llama3.1:8b"
    assert s.audit_concurrency == 2
    assert s.db_path == Path("D:/x") / "auditor.db"
