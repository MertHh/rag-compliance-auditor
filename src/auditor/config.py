import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    qdrant_url: str | None
    collection: str
    embed_model: str
    rerank_model: str
    device: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("AUDITOR_DATA_DIR", "data")),
            qdrant_url=os.environ.get("QDRANT_URL") or None,
            collection=os.environ.get("AUDITOR_COLLECTION", "chunks"),
            embed_model=os.environ.get("EMBED_MODEL", "BAAI/bge-m3"),
            rerank_model=os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
            device=os.environ.get("AUDITOR_DEVICE") or None,
        )
