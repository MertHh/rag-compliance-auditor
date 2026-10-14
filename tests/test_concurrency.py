import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fakes import CONTRACT_PAGES, FakeEmbedder, FakeReranker, FakeSparseEncoder

from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.indexer import Indexer
from auditor.retrieval.pipeline import Retriever
from auditor.storage.docstore import DocumentStore


class OverlapDetector:
    """Wraps an object and counts calls that start while another call is still running."""

    def __init__(self, inner):
        self._inner = inner
        self._guard = threading.Lock()
        self._active = 0
        self.overlaps = 0
        self.calls = 0

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            with self._guard:
                self._active += 1
                self.calls += 1
                if self._active > 1:
                    self.overlaps += 1
            try:
                time.sleep(0.002)
                return attr(*args, **kwargs)
            finally:
                with self._guard:
                    self._active -= 1

        return wrapped


def test_searches_and_ingest_never_use_the_store_at_once(tmp_path, make_pdf, sample_contract):
    store = OverlapDetector(QdrantStore.in_memory())
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse = FakeEmbedder(), FakeSparseEncoder()
    lock = threading.Lock()
    indexer = Indexer(store, embedder, sparse, docstore, lock=lock)
    retriever = Retriever(store, embedder, sparse, FakeReranker(), docstore, lock)
    indexer.ingest_pdf(make_pdf(tmp_path / "a.pdf", CONTRACT_PAGES))

    with ThreadPoolExecutor(max_workers=8) as pool:
        searches = [pool.submit(retriever.search, "total liability fees") for _ in range(12)]
        ingest = pool.submit(indexer.ingest_text, sample_contract, "b.txt")
        results = [future.result() for future in searches]
        assert ingest.result().chunk_count > 0

    assert store.overlaps == 0
    assert store.calls > 13
    assert all(result.chunks for result in results)


def test_retriever_serializes_its_own_searches(tmp_path, make_pdf):
    store = OverlapDetector(QdrantStore.in_memory())
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse = FakeEmbedder(), FakeSparseEncoder()
    Indexer(store, embedder, sparse, docstore).ingest_pdf(make_pdf(tmp_path / "a.pdf", CONTRACT_PAGES))
    store.overlaps = 0
    retriever = Retriever(store, embedder, sparse, FakeReranker(), docstore)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: retriever.search("liability"), range(10)))

    assert store.overlaps == 0
