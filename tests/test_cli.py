import pytest
from fakes import FakeEmbedder, FakeReranker, FakeSparseEncoder

from auditor.cli import main
from auditor.index.qdrant_store import QdrantStore
from auditor.ingestion.indexer import Indexer
from auditor.retrieval.pipeline import Retriever
from auditor.services import Services
from auditor.storage.docstore import DocumentStore

PAGES = [
    [("1. Definitions", 11),
     ("Services means the consulting services described in Exhibit A.", 11)],
    [("2. Liability", 11),
     ("The total liability shall not exceed the fees paid in twelve months.", 11)],
]


@pytest.fixture
def services(tmp_path):
    store = QdrantStore.in_memory()
    docstore = DocumentStore(tmp_path / "docs")
    embedder, sparse = FakeEmbedder(), FakeSparseEncoder()
    return Services(
        indexer=Indexer(store, embedder, sparse, docstore),
        retriever=Retriever(store, embedder, sparse, FakeReranker(), docstore),
        docstore=docstore,
        store=store,
    )


def test_ingest_then_search(services, make_pdf, tmp_path, capsys):
    path = make_pdf(tmp_path / "c.pdf", PAGES)
    assert main(["ingest", str(path)], services) == 0
    out = capsys.readouterr().out
    assert "indexed 2 chunks" in out

    assert main(["ingest", str(path)], services) == 0
    assert "already indexed" in capsys.readouterr().out

    assert main(["search", "total liability fees", "--top", "1"], services) == 0
    out = capsys.readouterr().out
    assert "1. [2]" in out
    assert "p[2]" in out
    assert "rerank=" in out
    assert "The total liability shall not exceed" in out


def test_search_modes_and_no_rerank(services, make_pdf, tmp_path, capsys):
    main(["ingest", str(make_pdf(tmp_path / "c.pdf", PAGES))], services)
    capsys.readouterr()
    assert main(["search", "liability", "--mode", "bm25", "--no-rerank"], services) == 0
    out = capsys.readouterr().out
    assert "bm25=#1" in out
    assert "dense=-" in out
    assert "rerank=-" in out


def test_search_with_no_results_says_so(services, capsys):
    assert main(["search", "liability"], services) == 0
    assert "no sufficient evidence" in capsys.readouterr().out


def test_ingest_errors_exit_with_1_and_message(services, tmp_path, capsys):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    assert main(["ingest", str(broken)], services) == 1
    assert "error:" in capsys.readouterr().err
    assert main(["ingest", str(tmp_path / "missing.pdf")], services) == 1
    assert "error:" in capsys.readouterr().err
