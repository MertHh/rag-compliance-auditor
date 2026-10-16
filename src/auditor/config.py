import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _optional_flag(name: str) -> bool | None:
    raw = os.environ.get(name, "").strip()
    return _flag(name) if raw else None


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    qdrant_url: str | None
    collection: str
    embed_model: str
    rerank_model: str
    device: str | None
    provider: str
    openai_eval_model: str | None
    openai_small_model: str | None
    openai_prices: str
    ollama_host: str
    ollama_model: str
    ollama_num_ctx: int
    playbooks_dir: Path
    audit_concurrency: int
    benchmarks_dir: Path
    context_prefix: bool
    rerank_device: str | None
    ollama_think: bool | None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "auditor.db"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("AUDITOR_DATA_DIR", "data")),
            qdrant_url=os.environ.get("QDRANT_URL") or None,
            collection=os.environ.get("AUDITOR_COLLECTION", "chunks"),
            embed_model=os.environ.get("EMBED_MODEL", "BAAI/bge-m3"),
            rerank_model=os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
            device=os.environ.get("AUDITOR_DEVICE") or None,
            provider=os.environ.get("AUDITOR_PROVIDER", "openai"),
            openai_eval_model=os.environ.get("OPENAI_EVAL_MODEL") or None,
            openai_small_model=os.environ.get("OPENAI_SMALL_MODEL") or None,
            openai_prices=os.environ.get("OPENAI_PRICES", ""),
            ollama_host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.environ.get("OLLAMA_MODEL", "qwen3:8b"),
            ollama_num_ctx=_int("OLLAMA_NUM_CTX", 16384),
            playbooks_dir=Path(os.environ.get("AUDITOR_PLAYBOOKS", "playbooks")),
            audit_concurrency=_int("AUDIT_CONCURRENCY", 4),
            benchmarks_dir=Path(os.environ.get("AUDITOR_BENCHMARKS", "benchmarks/results")),
            context_prefix=_flag("AUDITOR_CONTEXT_PREFIX"),
            rerank_device=os.environ.get("RERANK_DEVICE") or None,
            ollama_think=_optional_flag("OLLAMA_THINK"),
        )
