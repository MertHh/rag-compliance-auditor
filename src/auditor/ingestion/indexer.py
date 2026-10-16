from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from auditor.index.embedder import Embedder, SparseEncoder
from auditor.index.store import VectorStore
from auditor.ingestion.chunker import Chunk, build_chunks
from auditor.ingestion.parser import ParsedDocument, parse_pdf, parse_text
from auditor.ingestion.structure import detect_sections
from auditor.storage.docstore import DocumentStore

Contextualizer = Callable[[ParsedDocument, Chunk], str]
MetadataFn = Callable[[ParsedDocument], dict]


class EmptyDocumentError(Exception):
    pass


@dataclass
class IngestResult:
    document_id: str
    chunk_count: int
    already_indexed: bool


class Indexer:
    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        sparse_encoder: SparseEncoder,
        docstore: DocumentStore,
        *,
        max_child_tokens: int = 400,
        max_parent_tokens: int = 2000,
        contextualizer: Contextualizer | None = None,
        chunker: Callable[[ParsedDocument], list[Chunk]] | None = None,
        lock: threading.Lock | None = None,
    ):
        self._store = store
        self._embedder = embedder
        self._sparse = sparse_encoder
        self._docstore = docstore
        self._max_child_tokens = max_child_tokens
        self._max_parent_tokens = max_parent_tokens
        self._contextualizer = contextualizer
        self._chunker = chunker
        self._lock = lock or threading.Lock()

    def ingest_pdf(self, path: str | Path, metadata: dict | None = None, *,
                   extract_metadata: MetadataFn | None = None) -> IngestResult:
        doc = parse_pdf(path)
        return self._index(doc, metadata, Path(path).read_bytes(), extract_metadata)

    def ingest_text(self, text: str, filename: str, metadata: dict | None = None, *,
                    extract_metadata: MetadataFn | None = None) -> IngestResult:
        return self._index(parse_text(text, filename), metadata, None, extract_metadata)

    def is_indexed(self, document_id: str) -> bool:
        # An upsert interrupted between batches leaves fewer points than chunks: not indexed.
        with self._lock:
            if not self._docstore.exists(document_id):
                return False
            points = self._store.document_point_count(document_id)
            expected = self._docstore.chunk_count(document_id)
            return points > 0 and (expected is None or points == expected)

    def _index(self, doc: ParsedDocument, metadata: dict | None, source_pdf: bytes | None,
               extract_metadata: MetadataFn | None) -> IngestResult:
        if self.is_indexed(doc.document_id):
            return IngestResult(doc.document_id, 0, True)

        if self._chunker is not None:
            chunks = self._chunker(doc)
        else:
            chunks = build_chunks(
                doc, detect_sections(doc.lines), self._max_child_tokens, self._max_parent_tokens
            )
        if not chunks:
            raise EmptyDocumentError(f"{doc.filename}: document has no text to index")

        # A field the caller left empty (None) must not erase an extracted value.
        given = {key: value for key, value in (metadata or {}).items() if value is not None}
        meta = {
            "filename": doc.filename,
            "doc_type": None,
            "date": None,
            "parties": [],
            "jurisdiction": None,
            **(extract_metadata(doc) if extract_metadata else {}),
            **given,
        }
        if self._contextualizer:
            for chunk in chunks:
                chunk.context_prefix = self._contextualizer(doc, chunk)
        texts = [
            f"{chunk.context_prefix}\n\n{chunk.text}" if chunk.context_prefix else chunk.text
            for chunk in chunks
        ]

        # Save the text before the vectors: a search hit must always have a
        # document behind it. A failed upsert is retried by the next ingest.
        # Metadata extraction (an LLM call) stays outside the lock.
        with self._lock:
            self._docstore.save(doc, meta, source_pdf, chunk_count=len(chunks))
            self._store.ensure_collection(self._embedder.dim)
            self._store.delete_document(doc.document_id)
            self._store.upsert(
                chunks,
                self._embedder.embed_documents(texts),
                self._sparse.encode_documents(texts),
                meta,
            )
        return IngestResult(doc.document_id, len(chunks), False)
