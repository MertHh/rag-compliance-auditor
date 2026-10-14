import math
import re
import threading
import zlib

from auditor.index.store import SparseVec
from auditor.llm.base import LLMError, LLMResult, ProviderUnavailableError, Usage

_WORD = re.compile(r"\w+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _word_id(word: str) -> int:
    return zlib.crc32(word.encode("utf-8"))


class FakeEmbedder:
    dim = 64

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in _words(text):
            v[_word_id(word) % self.dim] += 1.0
        if not any(v):
            v[0] = 1.0
        norm = math.sqrt(sum(x * x for x in v))
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class FakeSparseEncoder:
    def _vec(self, text: str) -> SparseVec:
        counts: dict[int, float] = {}
        for word in _words(text):
            counts[_word_id(word)] = counts.get(_word_id(word), 0.0) + 1.0
        indices = sorted(counts)
        return SparseVec(indices, [counts[i] for i in indices])

    def encode_documents(self, texts: list[str]) -> list[SparseVec]:
        return [self._vec(t) for t in texts]

    def encode_query(self, text: str) -> SparseVec:
        return self._vec(text)


class FakeReranker:
    def score(self, query: str, texts: list[str]) -> list[float]:
        wanted = set(_words(query))
        if not wanted:
            return [0.0 for _ in texts]
        return [len(wanted & set(_words(t))) / len(wanted) for t in texts]


class FakeLLM:
    """Answers by schema name. A handler is a fixed value, an exception to raise,
    or a callable taking the user prompt and returning either."""

    name = "fake"

    def __init__(self, handlers: dict | None = None, unavailable: str | None = None):
        self.handlers = dict(handlers or {})
        self.unavailable = unavailable
        self.calls: list[tuple[str, str, str]] = []
        self._lock = threading.Lock()

    def model_for(self, tier):
        return f"fake-{tier}"

    def check_available(self):
        if self.unavailable:
            raise ProviderUnavailableError(self.unavailable)

    def complete(self, system, user, schema, tier):
        with self._lock:
            self.calls.append((schema.__name__, tier, user))
        handler = self.handlers.get(schema.__name__)
        if handler is None:
            raise LLMError(f"no fake response for {schema.__name__}")
        value = handler(user) if callable(handler) else handler
        if isinstance(value, Exception):
            raise value
        return LLMResult(value, self.model_for(tier), Usage(100, 20, 0.01))

    def count(self, schema_name: str) -> int:
        return sum(1 for name, _, _ in self.calls if name == schema_name)


def sequence(*values):
    """Handler returning the values in order, then repeating the last one."""
    items = list(values)
    lock = threading.Lock()

    def next_value(_user):
        with lock:
            return items.pop(0) if len(items) > 1 else items[0]

    return next_value


CONTRACT_PAGES = [
    [("1. Definitions", 11),
     ("Services means the consulting services described in Exhibit A.", 11)],
    [("2. Liability", 11),
     ("The total liability shall not exceed the fees paid in twelve months.", 11)],
]
LIABILITY_LINE = "The total liability shall not exceed the fees paid in twelve months."


def by_rule(responses: dict):
    """Handler choosing the response by the rule title in the prompt."""
    def handler(user):
        for title, value in responses.items():
            if f"Rule: {title}\n" in user:
                return value
        raise AssertionError(f"no fake response for prompt: {user[:80]!r}")
    return handler


def audit_llm(**overrides) -> FakeLLM:
    """Responses for the test playbook in conftest: liability found, confidentiality missing."""
    from auditor.audit.prompts import Evaluation, Relevance, RewrittenQueries
    from auditor.ingestion.metadata import DocumentMetadata
    from auditor.qa.answer import QAOutput

    handlers = {
        "Evaluation": by_rule({
            "Liability cap": Evaluation(clause_found=True, matches_criteria=True,
                                        reasoning="Liability is capped at fees paid.",
                                        quotes=[LIABILITY_LINE]),
            "Confidentiality": Evaluation(clause_found=False, matches_criteria=False,
                                          reasoning="No confidentiality clause.", quotes=[]),
        }),
        "Relevance": Relevance(relevant=False),
        "RewrittenQueries": RewrittenQueries(queries=["secret information"]),
        "QAOutput": QAOutput(answer="Liability is capped at the fees paid in twelve months.",
                             quotes=[LIABILITY_LINE]),
        "DocumentMetadata": DocumentMetadata(doc_type="Services Agreement", date="2024-03-01",
                                             parties=["Acme Corp"], jurisdiction=None),
    }
    handlers.update(overrides)
    return FakeLLM(handlers)


def fake_services(tmp_path, playbooks_dir, llm, benchmarks_dir=None, provider=None):
    """Services wired with in-memory Qdrant, fake models and one fake LLM for every provider."""
    from auditor.audit.runner import Auditor
    from auditor.index.qdrant_store import QdrantStore
    from auditor.ingestion.indexer import Indexer
    from auditor.retrieval.pipeline import Retriever
    from auditor.services import Services
    from auditor.storage.db import AuditStore
    from auditor.storage.docstore import DocumentStore

    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse = FakeEmbedder(), FakeSparseEncoder()
    lock = threading.Lock()
    retriever = Retriever(store, embedder, sparse, FakeReranker(), docstore, lock)
    audits = AuditStore(tmp_path / "auditor.db")

    if provider is None:
        def provider(name):
            return llm

    return Services(
        indexer=Indexer(store, embedder, sparse, docstore, lock=lock),
        retriever=retriever,
        docstore=docstore,
        store=store,
        audits=audits,
        auditor=Auditor(retriever, docstore, audits, playbooks_dir, provider),
        provider=provider,
        default_provider="openai",
        playbooks_dir=playbooks_dir,
        benchmarks_dir=benchmarks_dir or tmp_path / "benchmarks",
    )
