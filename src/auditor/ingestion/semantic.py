"""Semantic chunking for the benchmark comparison: start a new chunk where the next
sentence's embedding moves furthest from the previous one. Benchmark only — it calls the
embedder outside the indexer's store lock, so the API keeps the structural chunker."""

import math
import uuid

from auditor.index.embedder import Embedder
from auditor.ingestion.chunker import (
    _PARA_SEP,
    _SENT_SEP,
    Chunk,
    Span,
    _hard_split,
    _split_on,
    _trim,
    locate,
)
from auditor.ingestion.parser import ParsedDocument
from auditor.tokens import count_tokens


def sentence_spans(text: str, max_tokens: int) -> list[Span]:
    spans: list[Span] = []
    for p_start, p_end in _split_on(text, 0, len(text), _PARA_SEP):
        for s_start, s_end in _split_on(text, p_start, p_end, _SENT_SEP):
            start, end = _trim(text, s_start, s_end)
            if start >= end:
                continue
            if count_tokens(text[start:end]) <= max_tokens:
                spans.append((start, end))
            else:
                spans.extend(_hard_split(text, start, end, max_tokens))
    return spans


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(q / 100 * len(ordered)) - 1)
    return ordered[index]


def _chunk(doc: ParsedDocument, start: int, end: int) -> Chunk:
    boxes = locate(doc, start, end)
    return Chunk(
        chunk_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc.document_id}:semantic:{start}-{end}")),
        document_id=doc.document_id,
        text=doc.text[start:end],
        char_start=start,
        char_end=end,
        pages=sorted({box.page for box in boxes}),
        bboxes=boxes,
        section_title="",
        section_path="",
        parent_id=f"{doc.document_id}:{start}-{end}",
        parent_start=start,
        parent_end=end,
        parent_section_path="",
    )


def build_semantic_chunks(doc: ParsedDocument, embedder: Embedder, max_tokens: int = 400,
                          breakpoint_percentile: float = 90.0) -> list[Chunk]:
    units = sentence_spans(doc.text, max_tokens)
    if not units:
        return []
    vectors = embedder.embed_documents([doc.text[s:e] for s, e in units])
    # Embeddings are normalized, so the dot product is the cosine similarity.
    distances = [1.0 - sum(a * b for a, b in zip(vectors[i], vectors[i + 1]))
                 for i in range(len(units) - 1)]
    cut = percentile(distances, breakpoint_percentile) if distances else math.inf
    groups: list[Span] = []
    start, end = units[0]
    for i in range(1, len(units)):
        u_start, u_end = units[i]
        if distances[i - 1] >= cut or count_tokens(doc.text[start:u_end]) > max_tokens:
            groups.append((start, end))
            start = u_start
        end = u_end
    groups.append((start, end))
    return [_chunk(doc, s, e) for s, e in groups]
