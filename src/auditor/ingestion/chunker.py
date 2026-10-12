import re
import uuid
from dataclasses import dataclass

from auditor.ingestion.parser import ParsedDocument
from auditor.ingestion.structure import Section
from auditor.tokens import TOKEN_RE, count_tokens

_PARA_SEP = re.compile(r"\n\s*\n")
_SENT_SEP = re.compile(r"(?<=[.;:!?])\s+")

Span = tuple[int, int]


@dataclass(frozen=True)
class PageBox:
    page: int
    bbox: tuple[float, float, float, float]


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    char_start: int
    char_end: int
    pages: list[int]
    bboxes: list[PageBox]
    section_title: str
    section_path: str
    parent_id: str
    parent_start: int
    parent_end: int
    parent_section_path: str
    context_prefix: str = ""


def _trim(text: str, start: int, end: int) -> Span:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _split_on(text: str, start: int, end: int, sep: re.Pattern) -> list[Span]:
    spans, pos = [], start
    for m in sep.finditer(text, start, end):
        if m.start() > pos:
            spans.append((pos, m.start()))
        pos = m.end()
    if pos < end:
        spans.append((pos, end))
    return spans


def _hard_split(text: str, start: int, end: int, max_tokens: int) -> list[Span]:
    tokens = list(TOKEN_RE.finditer(text, start, end))
    return [
        (tokens[i].start(), tokens[min(i + max_tokens, len(tokens)) - 1].end())
        for i in range(0, len(tokens), max_tokens)
    ]


def _pack(text: str, units: list[Span], max_tokens: int) -> list[Span]:
    out: list[Span] = []
    current: Span | None = None
    for start, end in units:
        if current is None:
            current = (start, end)
        elif count_tokens(text[current[0]:end]) <= max_tokens:
            current = (current[0], end)
        else:
            out.append(current)
            current = (start, end)
    if current is not None:
        out.append(current)
    return out


def split_span(text: str, start: int, end: int, max_tokens: int) -> list[Span]:
    if count_tokens(text[start:end]) <= max_tokens:
        return [(start, end)]
    units: list[Span] = []
    for p_start, p_end in _split_on(text, start, end, _PARA_SEP):
        if count_tokens(text[p_start:p_end]) <= max_tokens:
            units.append((p_start, p_end))
            continue
        for s_start, s_end in _split_on(text, p_start, p_end, _SENT_SEP):
            if count_tokens(text[s_start:s_end]) <= max_tokens:
                units.append((s_start, s_end))
            else:
                units.extend(_hard_split(text, s_start, s_end, max_tokens))
    return _pack(text, units, max_tokens)


def locate(doc: ParsedDocument, start: int, end: int) -> list[PageBox]:
    return [
        PageBox(line.page, line.bbox)
        for line in doc.lines
        if line.bbox is not None and line.char_start < end and line.char_end > start
    ]


def _line_span(doc: ParsedDocument, line_start: int, line_end: int) -> Span:
    return doc.lines[line_start].char_start, doc.lines[line_end - 1].char_end


def _subtree_end(sections: list[Section], i: int) -> int:
    for j in range(i + 1, len(sections)):
        if sections[j].level <= sections[i].level:
            return sections[j].line_start
    return sections[-1].line_end


def _ancestors(sections: list[Section], i: int) -> list[int]:
    chain, level = [], sections[i].level
    for j in range(i - 1, -1, -1):
        if sections[j].level < level:
            chain.append(j)
            level = sections[j].level
    return list(reversed(chain))


def _pick_parent(
    doc: ParsedDocument, sections: list[Section], i: int, max_tokens: int
) -> tuple[int, int, str] | None:
    for idx in _ancestors(sections, i) + [i]:
        raw = _line_span(doc, sections[idx].line_start, _subtree_end(sections, idx))
        start, end = _trim(doc.text, *raw)
        if start < end and count_tokens(doc.text[start:end]) <= max_tokens:
            return start, end, sections[idx].path
    return None


def build_chunks(
    doc: ParsedDocument,
    sections: list[Section],
    max_child_tokens: int = 400,
    max_parent_tokens: int = 2000,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for i, section in enumerate(sections):
        if section.line_start >= section.line_end:
            continue
        start, end = _trim(doc.text, *_line_span(doc, section.line_start, section.line_end))
        if start >= end:
            continue
        parent = _pick_parent(doc, sections, i, max_parent_tokens)
        for raw_start, raw_end in split_span(doc.text, start, end, max_child_tokens):
            c_start, c_end = _trim(doc.text, raw_start, raw_end)
            if c_start >= c_end:
                continue
            p_start, p_end, p_path = parent or (c_start, c_end, section.path)
            boxes = locate(doc, c_start, c_end)
            chunks.append(Chunk(
                chunk_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc.document_id}:{c_start}-{c_end}")),
                document_id=doc.document_id,
                text=doc.text[c_start:c_end],
                char_start=c_start,
                char_end=c_end,
                pages=sorted({box.page for box in boxes}),
                bboxes=boxes,
                section_title=section.title,
                section_path=section.path,
                parent_id=f"{doc.document_id}:{p_start}-{p_end}",
                parent_start=p_start,
                parent_end=p_end,
                parent_section_path=p_path,
            ))
    return chunks
