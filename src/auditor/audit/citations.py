from dataclasses import dataclass

from auditor.ingestion.chunker import PageBox
from auditor.ingestion.parser import ParsedDocument
from auditor.retrieval.pipeline import ParentPassage
from auditor.tokens import count_tokens

MIN_QUOTE_TOKENS = 4

_UNIFY = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    " ": " ",
})
_EDGE_CHARS = " \"'.…"


@dataclass
class Citation:
    quote: str
    document_id: str
    char_start: int
    char_end: int
    page: int | None
    section_path: str
    bboxes: list[PageBox]

    def to_dict(self) -> dict:
        return {
            "quote": self.quote,
            "document_id": self.document_id,
            "page": self.page,
            "section_path": self.section_path,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "bboxes": [{"page": box.page, "bbox": list(box.bbox)} for box in self.bboxes],
        }


def _normalize(text: str) -> tuple[str, list[int]]:
    """Unify quote characters and collapse whitespace runs to one space.
    Returns the normalized text and the source index of each of its characters."""
    chars: list[str] = []
    index: list[int] = []
    previous_space = False
    for i, ch in enumerate(text.translate(_UNIFY)):
        if ch.isspace():
            if previous_space:
                continue
            ch, previous_space = " ", True
        else:
            previous_space = False
        chars.append(ch)
        index.append(i)
    return "".join(chars), index


def _locate(haystack: str, index: list[int], quote: str,
            prefer: list[tuple[int, int]]) -> tuple[int, int] | None:
    needle = _normalize(quote)[0].strip(_EDGE_CHARS)
    if count_tokens(needle) < MIN_QUOTE_TOKENS:
        return None
    spans = []
    pos = haystack.find(needle)
    while pos != -1:
        spans.append((index[pos], index[pos + len(needle) - 1] + 1))
        pos = haystack.find(needle, pos + 1)
    for start, end in spans:
        if any(a <= start and end <= b for a, b in prefer):
            return start, end
    return spans[0] if spans else None


def verify_quotes(doc: ParsedDocument, quotes: list[str],
                  passages: list[ParentPassage]) -> list[Citation]:
    haystack, index = _normalize(doc.text)
    own = [p for p in passages if p.document_id == doc.document_id]
    ranges = [(p.char_start, p.char_end) for p in own]
    citations: list[Citation] = []
    seen: set[tuple[int, int]] = set()
    for quote in quotes:
        span = _locate(haystack, index, quote, ranges)
        if span is None or span in seen:
            continue
        seen.add(span)
        start, end = span
        touched = [line for line in doc.lines
                   if line.page is not None and line.char_start < end and start < line.char_end]
        section = next((p.section_path for p in own if p.char_start <= start < p.char_end), "")
        citations.append(Citation(
            quote=doc.text[start:end],
            document_id=doc.document_id,
            char_start=start,
            char_end=end,
            page=touched[0].page if touched else None,
            section_path=section,
            bboxes=[PageBox(line.page, line.bbox) for line in touched if line.bbox is not None],
        ))
    return citations
