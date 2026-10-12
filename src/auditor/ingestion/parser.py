import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

MIN_CHARS_PER_PAGE = 50
LABEL_MAX_GAP = 72.0

_LABEL = re.compile(
    r"^(?:(?:ARTICLE|Article|SECTION|Section|MADDE|Madde)\s+)?"
    r"(?:[IVXLCDM]+|\d{1,3}(?:\.\d{1,3})*)[.)]?$"
)

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


def _page_entries(page) -> list[dict]:
    entries = []
    for block_index, block in enumerate(page.get_text("dict", sort=True)["blocks"]):
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            text = "".join(span["text"] for span in line["spans"]).strip()
            if not text:
                continue
            entries.append({
                "text": text,
                "bbox": tuple(round(v, 2) for v in line["bbox"]),
                "size": round(max(span["size"] for span in line["spans"]), 2),
                "block": block_index,
            })
    return entries


def _same_baseline(a: BBox, b: BBox) -> bool:
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    return overlap > 0.5 * min(a[3] - a[1], b[3] - b[1])


def _join_labels(entries: list[dict]) -> list[dict]:
    # A hanging-indent clause number ("1.") is extracted as its own line; join it
    # to the text on the same baseline so structure detection sees "1. Title".
    merged: set[int] = set()
    for i, label in enumerate(entries):
        if not _LABEL.match(label["text"]):
            continue
        best: tuple[float, int] | None = None
        for j, other in enumerate(entries):
            if j == i or j in merged:
                continue
            gap = other["bbox"][0] - label["bbox"][2]
            if 0 <= gap <= LABEL_MAX_GAP and _same_baseline(label["bbox"], other["bbox"]):
                if best is None or gap < best[0]:
                    best = (gap, j)
        if best is None:
            continue
        target = entries[best[1]]
        a, b = label["bbox"], target["bbox"]
        target["text"] = label["text"] + " " + target["text"]
        target["bbox"] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
        target["size"] = max(label["size"], target["size"])
        merged.add(i)
    return [entry for i, entry in enumerate(entries) if i not in merged]


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
    try:
        with pdf:
            if not pdf.is_pdf:
                raise InvalidPdfError(f"{path.name}: not a PDF file")
            if pdf.needs_pass:
                raise InvalidPdfError(f"{path.name}: PDF is password protected")
            if pdf.page_count == 0:
                raise InvalidPdfError(f"{path.name}: PDF has no pages")
            raw: list[tuple[str, int | None, BBox | None, float | None]] = []
            for page_index, page in enumerate(pdf):
                last_block = None
                for entry in _join_labels(_page_entries(page)):
                    if entry["block"] != last_block and raw:
                        raw.append(("", None, None, None))
                    last_block = entry["block"]
                    raw.append((entry["text"], page_index + 1, entry["bbox"], entry["size"]))
            page_count = pdf.page_count
    except InvalidPdfError:
        raise
    except Exception as exc:
        raise InvalidPdfError(f"{path.name}: PDF is damaged and cannot be read") from exc
    text, lines = _assemble(raw)
    if len(text.strip()) < MIN_CHARS_PER_PAGE * page_count:
        raise ScannedPdfError(f"{path.name}: document is scanned, no text layer")
    return ParsedDocument(hashlib.sha256(data).hexdigest(), path.name, text, lines, page_count)
