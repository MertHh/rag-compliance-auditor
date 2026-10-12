import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf

MIN_CHARS_PER_PAGE = 50

BBox = tuple[float, float, float, float]


class InvalidPdfError(Exception):
    pass


class ScannedPdfError(Exception):
    pass


@dataclass
class Line:
    text: str
    page: int | None
    bbox: BBox | None
    font_size: float | None
    char_start: int
    char_end: int


@dataclass
class ParsedDocument:
    document_id: str
    filename: str
    text: str
    lines: list[Line]
    page_count: int


def _assemble(raw: list[tuple[str, int | None, BBox | None, float | None]]) -> tuple[str, list[Line]]:
    lines, pos = [], 0
    for text, page, bbox, size in raw:
        lines.append(Line(text, page, bbox, size, pos, pos + len(text)))
        pos += len(text) + 1
    return "\n".join(line.text for line in lines), lines


def parse_text(text: str, filename: str) -> ParsedDocument:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    document_id = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    full, lines = _assemble([(t, None, None, None) for t in normalized.split("\n")])
    return ParsedDocument(document_id, filename, full, lines, 0)


def parse_pdf(path: str | Path) -> ParsedDocument:
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InvalidPdfError(f"{path.name}: cannot read file") from exc
    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise InvalidPdfError(f"{path.name}: not a valid PDF") from exc
    with pdf:
        if pdf.needs_pass:
            raise InvalidPdfError(f"{path.name}: PDF is password protected")
        if pdf.page_count == 0:
            raise InvalidPdfError(f"{path.name}: PDF has no pages")
        raw: list[tuple[str, int | None, BBox | None, float | None]] = []
        for page_index, page in enumerate(pdf):
            for block in page.get_text("dict", sort=True)["blocks"]:
                if block.get("type") != 0:
                    continue
                block_lines = []
                for line in block["lines"]:
                    text = "".join(span["text"] for span in line["spans"]).strip()
                    if not text:
                        continue
                    size = max(span["size"] for span in line["spans"])
                    bbox = tuple(round(v, 2) for v in line["bbox"])
                    block_lines.append((text, page_index + 1, bbox, round(size, 2)))
                if block_lines:
                    if raw:
                        raw.append(("", None, None, None))
                    raw.extend(block_lines)
        page_count = pdf.page_count
    text, lines = _assemble(raw)
    if len(text.strip()) < MIN_CHARS_PER_PAGE * page_count:
        raise ScannedPdfError(f"{path.name}: document is scanned, no text layer")
    return ParsedDocument(hashlib.sha256(data).hexdigest(), path.name, text, lines, page_count)
