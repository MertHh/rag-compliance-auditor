from qdrant_client import QdrantClient, models

from auditor.index.store import Hit, SearchFilter, SparseVec, date_to_int
from auditor.ingestion.chunker import Chunk

DENSE = "dense"
SPARSE = "sparse"


def _meta_payload(doc_meta: dict) -> dict:
    return {
        "doc_type": doc_meta.get("doc_type"),
        "jurisdiction": doc_meta.get("jurisdiction"),
        "date": doc_meta.get("date"),
        "date_int": date_to_int(doc_meta.get("date")),
    }


def _chunk_payload(chunk: Chunk, doc_meta: dict) -> dict:
    return {
        "document_id": chunk.document_id,
        "text": chunk.text,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "pages": chunk.pages,
        "bboxes": [{"page": box.page, "bbox": list(box.bbox)} for box in chunk.bboxes],
        "section_title": chunk.section_title,
        "section_path": chunk.section_path,
        "parent_id": chunk.parent_id,
        "parent_start": chunk.parent_start,
        "parent_end": chunk.parent_end,
        "parent_section_path": chunk.parent_section_path,
        "context_prefix": chunk.context_prefix,
        **_meta_payload(doc_meta),
    }


def _document_filter(document_id: str) -> models.Filter:
    return models.Filter(must=[
        models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))
    ])


def _to_filter(flt: SearchFilter | None) -> models.Filter | None:
    if flt is None:
        return None
    must = []
    if flt.document_ids:
        must.append(models.FieldCondition(key="document_id", match=models.MatchAny(any=flt.document_ids)))
    if flt.doc_types:
        must.append(models.FieldCondition(key="doc_type", match=models.MatchAny(any=flt.doc_types)))
    if flt.jurisdictions:
        must.append(models.FieldCondition(key="jurisdiction", match=models.MatchAny(any=flt.jurisdictions)))
    if flt.date_from or flt.date_to:
        must.append(models.FieldCondition(
            key="date_int",
            range=models.Range(gte=date_to_int(flt.date_from), lte=date_to_int(flt.date_to)),
        ))
    return models.Filter(must=must) if must else None


class QdrantStore:
    def __init__(self, client: QdrantClient, collection: str = "chunks"):
        self._client = client
        self._collection = collection

    @classmethod
    def in_memory(cls, collection: str = "chunks") -> "QdrantStore":
        return cls(QdrantClient(":memory:"), collection)

    def _exists(self) -> bool:
        return self._client.collection_exists(self._collection)

    def ensure_collection(self, dense_dim: int) -> None:
        if self._exists():
            return
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config={DENSE: models.VectorParams(size=dense_dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        for field in ("document_id", "doc_type", "jurisdiction"):
            self._client.create_payload_index(
                self._collection, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD
            )
        self._client.create_payload_index(
            self._collection, field_name="date_int", field_schema=models.PayloadSchemaType.INTEGER
        )

    def upsert(self, chunks: list[Chunk], dense: list[list[float]],
               sparse: list[SparseVec], doc_meta: dict) -> None:
        points = [
            models.PointStruct(
                id=chunk.chunk_id,
                vector={
                    DENSE: dense_vec,
                    SPARSE: models.SparseVector(indices=sparse_vec.indices, values=sparse_vec.values),
                },
                payload=_chunk_payload(chunk, doc_meta),
            )
            for chunk, dense_vec, sparse_vec in zip(chunks, dense, sparse, strict=True)
        ]
        self._client.upsert(self._collection, points=points)

    def _query(self, query, using: str, limit: int, flt: SearchFilter | None) -> list[Hit]:
        if not self._exists():
            return []
        result = self._client.query_points(
            self._collection,
            query=query,
            using=using,
            query_filter=_to_filter(flt),
            limit=limit,
            with_payload=True,
        )
        return [Hit(str(p.id), float(p.score), p.payload or {}) for p in result.points]

    def search_dense(self, vector: list[float], limit: int,
                     flt: SearchFilter | None = None) -> list[Hit]:
        return self._query(vector, DENSE, limit, flt)

    def search_sparse(self, vector: SparseVec, limit: int,
                      flt: SearchFilter | None = None) -> list[Hit]:
        if not vector.indices:
            return []
        query = models.SparseVector(indices=vector.indices, values=vector.values)
        return self._query(query, SPARSE, limit, flt)

    def has_document(self, document_id: str) -> bool:
        if not self._exists():
            return False
        result = self._client.count(
            self._collection, count_filter=_document_filter(document_id), exact=True
        )
        return result.count > 0

    def delete_document(self, document_id: str) -> None:
        if not self._exists():
            return
        self._client.delete(
            self._collection,
            points_selector=models.FilterSelector(filter=_document_filter(document_id)),
        )

    def set_document_metadata(self, document_id: str, doc_meta: dict) -> None:
        if not self._exists():
            return
        self._client.set_payload(
            self._collection, payload=_meta_payload(doc_meta), points=_document_filter(document_id)
        )
