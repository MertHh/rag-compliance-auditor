import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from auditor.audit.nodes import AuditConfig
from auditor.audit.runner import Auditor
from auditor.config import Settings
from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.context import LLMContextualizer
from auditor.ingestion.indexer import Indexer
from auditor.lazy import Lazy
from auditor.llm.base import LLMProvider
from auditor.llm.factory import cached_provider_factory
from auditor.retrieval.pipeline import Retriever
from auditor.storage.db import AuditStore
from auditor.storage.docstore import DocumentStore


def _no_warm_up() -> None:
    pass


@dataclass
class Services:
    indexer: Indexer
    retriever: Retriever
    docstore: DocumentStore
    store: QdrantStore
    audits: AuditStore
    auditor: Auditor
    provider: Callable[[str], LLMProvider]
    default_provider: str = "openai"
    playbooks_dir: Path = Path("playbooks")
    benchmarks_dir: Path = Path("benchmarks/results")
    warm_up: Callable[[], None] = field(default=_no_warm_up)


def build_services(settings: Settings) -> Services:
    from qdrant_client import QdrantClient

    from auditor.index import embedder as embedders
    from auditor.retrieval import reranker as rerankers

    if settings.qdrant_url:
        client = QdrantClient(url=settings.qdrant_url, timeout=60)
    else:
        qdrant_dir = settings.data_dir / "qdrant"
        qdrant_dir.mkdir(parents=True, exist_ok=True)
        client = QdrantClient(path=str(qdrant_dir))

    store = QdrantStore(client, settings.collection)
    docstore = DocumentStore(settings.data_dir / "documents")
    # Models load on first use, so a cached audit or a document listing starts at once.
    embedder = Lazy(lambda: embedders.BgeM3Embedder(settings.embed_model, settings.device))
    sparse = Lazy(lambda: embedders.Bm25SparseEncoder())
    reranker = Lazy(lambda: rerankers.BgeReranker(settings.rerank_model, settings.device))
    lock = threading.Lock()
    retriever = Retriever(store, embedder, sparse, reranker, docstore, lock)
    audits = AuditStore(settings.db_path)
    provider = cached_provider_factory(settings)
    contextualizer = (LLMContextualizer(lambda: provider(settings.provider))
                      if settings.context_prefix else None)
    auditor = Auditor(retriever, docstore, audits, settings.playbooks_dir, provider,
                      AuditConfig(concurrency=settings.audit_concurrency))

    def warm_up() -> None:
        for model in (embedder, sparse, reranker):
            model.load()

    return Services(
        indexer=Indexer(store, embedder, sparse, docstore, lock=lock, contextualizer=contextualizer),
        retriever=retriever,
        docstore=docstore,
        store=store,
        audits=audits,
        auditor=auditor,
        provider=provider,
        default_provider=settings.provider,
        playbooks_dir=settings.playbooks_dir,
        benchmarks_dir=settings.benchmarks_dir,
        warm_up=warm_up,
    )
