from dataclasses import dataclass

from auditor.index.embedder import Embedder, SparseEncoder
from auditor.index.store import Hit, SearchFilter, VectorStore
from auditor.ingestion.chunker import PageBox
from auditor.retrieval.config import RetrievalConfig
from auditor.retrieval.fusion import rrf_fuse
from auditor.retrieval.reranker import Reranker
from auditor.storage.docstore import DocumentStore


@dataclass
class StageScores:
    bm25_rank: int | None
    bm25_score: float | None
    dense_rank: int | None
    dense_score: float | None
    rrf_score: float | None
    fused_rank: int
    rerank_score: float | None
    final_rank: int
    rank_change: int


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    text: str
    section_title: str
    section_path: str
    pages: list[int]
    bboxes: list[PageBox]
    char_start: int
    char_end: int
    parent_id: str
    scores: StageScores


@dataclass
class ParentPassage:
    parent_id: str
    document_id: str
    text: str
    char_start: int
    char_end: int
    section_path: str
    chunk_ids: list[str]


@dataclass
class RetrievalResult:
    query: str
    config: RetrievalConfig
    chunks: list[RetrievedChunk]
    parents: list[ParentPassage]
    insufficient_evidence: bool


def _positions(hits: list[Hit]) -> dict[str, tuple[int, float]]:
    return {hit.chunk_id: (rank, hit.score) for rank, hit in enumerate(hits, start=1)}


class Retriever:
    def __init__(self, store: VectorStore, embedder: Embedder, sparse_encoder: SparseEncoder,
                 reranker: Reranker, docstore: DocumentStore):
        self._store = store
        self._embedder = embedder
        self._sparse = sparse_encoder
        self._reranker = reranker
        self._docstore = docstore

    def search(self, query: str, config: RetrievalConfig | None = None,
               flt: SearchFilter | None = None) -> RetrievalResult:
        config = config or RetrievalConfig()
        if not query.strip():
            return RetrievalResult(query, config, [], [], True)

        bm25: list[Hit] = []
        dense: list[Hit] = []
        if config.mode in ("bm25", "hybrid"):
            bm25 = self._store.search_sparse(
                self._sparse.encode_query(query), config.candidate_k, flt
            )
        if config.mode in ("dense", "hybrid"):
            dense = self._store.search_dense(
                self._embedder.embed_query(query), config.candidate_k, flt
            )

        payloads = {hit.chunk_id: hit.payload for hit in [*bm25, *dense]}
        bm25_pos, dense_pos = _positions(bm25), _positions(dense)

        rrf: dict[str, float] = {}
        if config.mode == "hybrid":
            fused = rrf_fuse(
                [[h.chunk_id for h in bm25], [h.chunk_id for h in dense]], k=config.rrf_k
            )[:config.candidate_k]
            rrf = dict(fused)
            candidate_ids = [chunk_id for chunk_id, _ in fused]
        else:
            candidate_ids = [h.chunk_id for h in (bm25 if config.mode == "bm25" else dense)]
        fused_rank = {chunk_id: rank for rank, chunk_id in enumerate(candidate_ids, start=1)}

        rerank: dict[str, float] = {}
        ordered = candidate_ids
        if config.rerank and candidate_ids:
            scores = self._reranker.score(query, [payloads[c]["text"] for c in candidate_ids])
            rerank = dict(zip(candidate_ids, scores, strict=True))
            ordered = sorted(candidate_ids, key=lambda c: -rerank[c])
        final_ids = ordered[:config.final_k]

        chunks = []
        for final_rank, chunk_id in enumerate(final_ids, start=1):
            payload = payloads[chunk_id]
            bm25_rank, bm25_score = bm25_pos.get(chunk_id, (None, None))
            dense_rank, dense_score = dense_pos.get(chunk_id, (None, None))
            chunks.append(RetrievedChunk(
                chunk_id=chunk_id,
                document_id=payload["document_id"],
                text=payload["text"],
                section_title=payload["section_title"],
                section_path=payload["section_path"],
                pages=payload["pages"],
                bboxes=[PageBox(b["page"], tuple(b["bbox"])) for b in payload["bboxes"]],
                char_start=payload["char_start"],
                char_end=payload["char_end"],
                parent_id=payload["parent_id"],
                scores=StageScores(
                    bm25_rank=bm25_rank,
                    bm25_score=bm25_score,
                    dense_rank=dense_rank,
                    dense_score=dense_score,
                    rrf_score=rrf.get(chunk_id),
                    fused_rank=fused_rank[chunk_id],
                    rerank_score=rerank.get(chunk_id),
                    final_rank=final_rank,
                    rank_change=fused_rank[chunk_id] - final_rank,
                ),
            ))

        insufficient = not chunks or (
            config.rerank and chunks[0].scores.rerank_score < config.min_rerank_score
        )
        return RetrievalResult(query, config, chunks, self._expand(chunks, payloads), bool(insufficient))

    def _expand(self, chunks: list[RetrievedChunk], payloads: dict[str, dict]) -> list[ParentPassage]:
        parents: dict[str, ParentPassage] = {}
        for chunk in chunks:
            payload = payloads[chunk.chunk_id]
            parent = parents.get(chunk.parent_id)
            if parent is None:
                start, end = payload["parent_start"], payload["parent_end"]
                text = self._docstore.load(chunk.document_id).text[start:end]
                parent = ParentPassage(
                    parent_id=chunk.parent_id,
                    document_id=chunk.document_id,
                    text=text,
                    char_start=start,
                    char_end=end,
                    section_path=payload["parent_section_path"],
                    chunk_ids=[],
                )
                parents[chunk.parent_id] = parent
            parent.chunk_ids.append(chunk.chunk_id)
        return list(parents.values())
