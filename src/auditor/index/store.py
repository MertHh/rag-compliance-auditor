from dataclasses import dataclass
from datetime import date
from typing import Protocol

from auditor.ingestion.chunker import Chunk


@dataclass
class SparseVec:
    indices: list[int]
    values: list[float]


@dataclass
class SearchFilter:
    document_ids: list[str] | None = None
    doc_types: list[str] | None = None
    jurisdictions: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None


@dataclass
class Hit:
    chunk_id: str
    score: float
    payload: dict


class InvalidDateError(ValueError):
    pass


def date_to_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise InvalidDateError(f"date must be YYYY-MM-DD, got {value!r}") from exc
    return parsed.year * 10000 + parsed.month * 100 + parsed.day


class VectorStore(Protocol):
    def ensure_collection(self, dense_dim: int) -> None: ...

    def upsert(self, chunks: list[Chunk], dense: list[list[float]],
               sparse: list[SparseVec], doc_meta: dict) -> None: ...

    def search_dense(self, vector: list[float], limit: int,
                     flt: SearchFilter | None = None) -> list[Hit]: ...

    def search_sparse(self, vector: SparseVec, limit: int,
                      flt: SearchFilter | None = None) -> list[Hit]: ...

    def has_document(self, document_id: str) -> bool: ...

    def delete_document(self, document_id: str) -> None: ...

    def set_document_metadata(self, document_id: str, doc_meta: dict) -> None: ...
