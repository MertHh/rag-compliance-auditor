import re
import statistics
from dataclasses import dataclass

from auditor.ingestion.parser import Line

_ARTICLE = re.compile(
    r"^(ARTICLE|Article|SECTION|Section|MADDE|Madde)\s+([IVXLCDM]+|\d{1,3})(?!\.\d)\b"
    r"\s*([.:\-–—]?)\s*(.*)$"
)
_QUOTES = "\"'“‘"
_NUMBERED = re.compile(r"^(\d{1,3}(?:\.\d{1,3})*)(\.?)\s+(\S.*)$")
_TITLE_END = re.compile(r"(?<=[.:;])\s")

FONT_HEADING_RATIO = 1.15
FONT_HEADING_MAX_CHARS = 100
TITLE_MAX_CHARS = 80


@dataclass
class Section:
    number: str | None
    title: str
    level: int
    path: str
    line_start: int
    line_end: int


def _titleish(rest: str) -> bool:
    return rest == "" or not rest[0].islower()


def _title(rest: str) -> str:
    return _TITLE_END.split(rest, maxsplit=1)[0].strip(" .:;-–—")[:TITLE_MAX_CHARS]


def _classify(text: str) -> tuple[str, str, str] | None:
    m = _ARTICLE.match(text)
    if m:
        keyword, number, separator, rest = m.groups()
        # "Section 9, Customer shall..." and a wrapped "...in Section 7." are
        # cross-references: a heading's title starts with a capital or a quote,
        # and a bare "Section 7." only counts when written as "SECTION 7.".
        if rest:
            is_heading = rest[0].isupper() or rest[0] in _QUOTES
        else:
            is_heading = separator != "." or keyword.isupper()
        if is_heading:
            return "article", number, _title(rest) or f"{keyword} {number}"
    m = _NUMBERED.match(text)
    if m:
        number, dot, rest = m.groups()
        if ("." in number or dot) and _titleish(rest):
            return "numbered", number, _title(rest)
    return None


def detect_sections(lines: list[Line]) -> list[Section]:
    classified = [_classify(line.text.strip()) for line in lines]
    offset = 1 if any(c and c[0] == "article" for c in classified) else 0
    sizes = [l.font_size for l in lines if l.font_size and l.text.strip()]
    body_size = statistics.median(sizes) if sizes else None

    heads: list[tuple[int, str | None, str, int]] = []
    for i, (line, c) in enumerate(zip(lines, classified)):
        text = line.text.strip()
        if c:
            kind, number, title = c
            level = 1 if kind == "article" else number.count(".") + 1 + offset
            heads.append((i, number, title, level))
        elif (
            body_size
            and line.font_size
            and line.font_size >= body_size * FONT_HEADING_RATIO
            and len(text) <= FONT_HEADING_MAX_CHARS
            and any(ch.isalpha() for ch in text)
        ):
            heads.append((i, None, text[:TITLE_MAX_CHARS], 1))

    if not heads:
        return [Section(None, "Document", 1, "Document", 0, len(lines))]

    sections: list[Section] = []
    first = heads[0][0]
    has_preamble = any(line.text.strip() for line in lines[:first])
    if has_preamble:
        sections.append(Section(None, "Preamble", 1, "Preamble", 0, first))

    stack: list[tuple[int, str]] = []
    for n, (i, number, title, level) in enumerate(heads):
        start = i if (n > 0 or has_preamble) else 0
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        label = number or title
        while stack and stack[-1][0] >= level:
            stack.pop()
        path = " > ".join([s[1] for s in stack] + [label])
        stack.append((level, label))
        sections.append(Section(number, title, level, path, start, end))
    return sections
