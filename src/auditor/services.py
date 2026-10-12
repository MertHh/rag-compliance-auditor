from dataclasses import dataclass

from auditor.config import Settings
from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.indexer import Indexer
from auditor.retrieval.pipeline import Retriever
from auditor.storage.docstore import DocumentStore


@dataclass
class Services:
    indexer: Indexer
    retriever: Retriever
    docstore: DocumentStore
    store: QdrantStore


def build_services(settings: Settings) -> Services:
    from qdrant_client import QdrantClient

    from auditor.index.embedder import BgeM3Embedder, Bm25SparseEncoder
    from auditor.retrieval.reranker import BgeReranker

    if settings.qdrant_url:
        client = QdrantClient(url=settings.qdrant_url)
    else:
        qdrant_dir = settings.data_dir / "qdrant"
        qdrant_dir.mkdir(parents=True, exist_ok=True)
        client = QdrantClient(path=str(qdrant_dir))

    store = QdrantStore(client, settings.collection)
    docstore = DocumentStore(settings.data_dir / "documents")
    embedder = BgeM3Embedder(settings.embed_model, settings.device)
    sparse = Bm25SparseEncoder()
    reranker = BgeReranker(settings.rerank_model, settings.device)
    return Services(
        indexer=Indexer(store, embedder, sparse, docstore),
        retriever=Retriever(store, embedder, sparse, reranker, docstore),
        docstore=docstore,
        store=store,
    )
