import logging
import threading
from typing import Callable

from pydantic import BaseModel

from auditor.ingestion.chunker import Chunk
from auditor.ingestion.metadata import first_pages_text
from auditor.ingestion.parser import ParsedDocument
from auditor.llm.base import LLMError, LLMProvider, ProviderUnavailableError, Usage, complete_with_retry

log = logging.getLogger(__name__)

CONTEXT_SYSTEM = (
    "You place a passage within its contract to improve search. Reply with one sentence of at "
    "most 30 words naming the contract type, the parties if stated, and what the passage is "
    "about. Do not quote the passage."
)


class ContextLine(BaseModel):
    sentence: str


class LLMContextualizer:
    """Writes one sentence that places a chunk in its contract; the indexer embeds it in
    front of the chunk text. The contract's opening comes first in every prompt so a
    provider that caches prompt prefixes bills the repeated part at a discount."""

    def __init__(self, provider_factory: Callable[[], LLMProvider], max_doc_chars: int = 6000):
        self._provider_factory = provider_factory
        self._max_doc_chars = max_doc_chars
        self._lock = threading.Lock()
        self.usage = Usage()
        self.failures = 0

    def __call__(self, doc: ParsedDocument, chunk: Chunk) -> str:
        prompt = (f"Contract opening:\n{first_pages_text(doc, max_chars=self._max_doc_chars)}\n\n"
                  f"Passage (section {chunk.section_path or '-'}):\n{chunk.text}")
        try:
            result = complete_with_retry(self._provider_factory(), CONTEXT_SYSTEM, prompt,
                                         ContextLine, "small")
        except (LLMError, ProviderUnavailableError) as exc:
            log.warning("context prefix failed for %s: %s", doc.filename, exc)
            with self._lock:
                self.failures += 1
            return ""
        with self._lock:
            self.usage = self.usage + result.usage
        return result.value.sentence.strip()
