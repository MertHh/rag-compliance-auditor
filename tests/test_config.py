from pathlib import Path

from auditor.config import Settings


def test_defaults(monkeypatch):
    for name in ("AUDITOR_DATA_DIR", "QDRANT_URL", "AUDITOR_COLLECTION",
                 "EMBED_MODEL", "RERANK_MODEL", "AUDITOR_DEVICE"):
        monkeypatch.delenv(name, raising=False)
    s = Settings.from_env()
    assert s.data_dir == Path("data")
    assert s.qdrant_url is None
    assert s.collection == "chunks"
    assert s.embed_model == "BAAI/bge-m3"
    assert s.rerank_model == "BAAI/bge-reranker-v2-m3"
    assert s.device is None


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("AUDITOR_DATA_DIR", "D:/x")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("AUDITOR_DEVICE", "cpu")
    s = Settings.from_env()
    assert s.data_dir == Path("D:/x")
    assert s.qdrant_url == "http://localhost:6333"
    assert s.device == "cpu"
