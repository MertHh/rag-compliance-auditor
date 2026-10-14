from dataclasses import dataclass
from typing import Callable

from auditor.audit.nodes import AuditConfig
from auditor.audit.runner import Auditor
from auditor.config import Settings
from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.indexer import Indexer
from auditor.llm.base import LLMProvider
from auditor.llm.factory import cached_provider_factory
from auditor.retrieval.pipeline import Retriever
from auditor.storage.db import AuditStore
from auditor.storage.docstore import DocumentStore


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


def build_services(settings: Settings) -> Services:
    from qdrant_client import QdrantClient

    from auditor.index.embedder import BgeM3Embedder, Bm25SparseEncoder
    from auditor.retrieval.reranker import BgeReranker

    if settings.qdrant_url:
        client = QdrantClient(url=settings.qdrant_url, timeout=60)
    else:
        qdrant_dir = settings.data_dir / "qdrant"
        qdrant_dir.mkdir(parents=True, exist_ok=True)
        client = QdrantClient(path=str(qdrant_dir))

    store = QdrantStore(client, settings.collection)
    docstore = DocumentStore(settings.data_dir / "documents")
    embedder = BgeM3Embedder(settings.embed_model, settings.device)
    sparse = Bm25SparseEncoder()
    reranker = BgeReranker(settings.rerank_model, settings.device)
    retriever = Retriever(store, embedder, sparse, reranker, docstore)
    audits = AuditStore(settings.db_path)
    provider = cached_provider_factory(settings)
    auditor = Auditor(retriever, docstore, audits, settings.playbooks_dir, provider,
                      AuditConfig(concurrency=settings.audit_concurrency))
    return Services(
        indexer=Indexer(store, embedder, sparse, docstore),
        retriever=retriever,
        docstore=docstore,
        store=store,
        audits=audits,
        auditor=auditor,
        provider=provider,
        default_provider=settings.provider,
    )
