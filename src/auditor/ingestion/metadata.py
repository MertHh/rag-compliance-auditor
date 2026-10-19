import logging

from pydantic import BaseModel

from auditor.index.store import InvalidDateError, date_to_int
from auditor.ingestion.parser import ParsedDocument
from auditor.llm.base import LLMError, LLMProvider, complete_with_retry

log = logging.getLogger(__name__)

MAX_PAGES = 2
MAX_CHARS = 8000

METADATA_SYSTEM = (
    "You extract metadata from the first pages of a document. doc_type is a short document type "
    "in English, such as 'Master Services Agreement', 'Research Article' or 'Security Policy'. "
    "date is the effective, signing or publication date as YYYY-MM-DD. parties are the legal "
    "names of the contracting parties, or for a document that is not a contract its authors or "
    "issuing organisations. jurisdiction is the governing law, such as 'New York' or 'England "
    "and Wales'. "
    "Use null, or an empty list for parties, when the text does not state a value."
)


class DocumentMetadata(BaseModel):
    doc_type: str | None
    date: str | None
    parties: list[str]
    jurisdiction: str | None


def first_pages_text(doc: ParsedDocument, max_pages: int = MAX_PAGES,
                     max_chars: int = MAX_CHARS) -> str:
    if doc.page_count:
        text = "\n".join(line.text for line in doc.lines
                         if line.page is not None and line.page <= max_pages)
    else:
        text = doc.text
    return text[:max_chars]


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _iso_date(value: str | None) -> str | None:
    try:
        return value if date_to_int(value) is not None else None
    except InvalidDateError:
        return None


class MetadataExtractor:
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    def __call__(self, doc: ParsedDocument) -> dict:
        text = first_pages_text(doc)
        if not text.strip():
            return {}
        try:
            result = complete_with_retry(self._provider, METADATA_SYSTEM, text,
                                         DocumentMetadata, "small")
        except LLMError as exc:
            log.warning("metadata extraction failed for %s: %s", doc.filename, exc)
            return {}
        meta = result.value
        values = {
            "doc_type": _clean(meta.doc_type),
            "date": _iso_date(_clean(meta.date)),
            "jurisdiction": _clean(meta.jurisdiction),
            "parties": list(dict.fromkeys(p.strip() for p in meta.parties if p.strip())),
        }
        return {key: value for key, value in values.items() if value}
