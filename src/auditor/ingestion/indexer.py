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
    ):
        self._store = store
        self._embedder = embedder
        self._sparse = sparse_encoder
        self._docstore = docstore
        self._max_child_tokens = max_child_tokens
        self._max_parent_tokens = max_parent_tokens
        self._contextualizer = contextualizer

    def ingest_pdf(self, path: str | Path, metadata: dict | None = None) -> IngestResult:
        doc = parse_pdf(path)
        return self._index(doc, metadata, Path(path).read_bytes())

    def ingest_text(self, text: str, filename: str, metadata: dict | None = None) -> IngestResult:
        return self._index(parse_text(text, filename), metadata, None)

    def _index(self, doc: ParsedDocument, metadata: dict | None,
               source_pdf: bytes | None) -> IngestResult:
        if self._docstore.exists(doc.document_id) and self._store.has_document(doc.document_id):
            return IngestResult(doc.document_id, 0, True)

        chunks = build_chunks(
            doc, detect_sections(doc.lines), self._max_child_tokens, self._max_parent_tokens
        )
        if not chunks:
            raise EmptyDocumentError(f"{doc.filename}: document has no text to index")

        meta = {
            "filename": doc.filename,
            "doc_type": None,
            "date": None,
            "parties": [],
            "jurisdiction": None,
            **(metadata or {}),
        }
        if self._contextualizer:
            for chunk in chunks:
                chunk.context_prefix = self._contextualizer(doc, chunk)
        texts = [
            f"{chunk.context_prefix}\n\n{chunk.text}" if chunk.context_prefix else chunk.text
            for chunk in chunks
        ]

        self._store.ensure_collection(self._embedder.dim)
        self._store.delete_document(doc.document_id)
        self._store.upsert(
            chunks,
            self._embedder.embed_documents(texts),
            self._sparse.encode_documents(texts),
            meta,
        )
        self._docstore.save(doc, meta, source_pdf)
        return IngestResult(doc.document_id, len(chunks), False)
