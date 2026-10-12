import argparse
import sys
from dataclasses import replace

from auditor.config import Settings
from auditor.ingestion.indexer import EmptyDocumentError
from auditor.ingestion.parser import InvalidPdfError, ScannedPdfError
from auditor.retrieval.config import RetrievalConfig
from auditor.services import Services, build_services


def _rank(rank: int | None) -> str:
    return f"#{rank}" if rank is not None else "-"


def _score(score: float | None) -> str:
    return f"{score:.3f}" if score is not None else "-"


def _ingest(services: Services, path: str) -> int:
    try:
        result = services.indexer.ingest_pdf(path)
    except (InvalidPdfError, ScannedPdfError, EmptyDocumentError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if result.already_indexed:
        print(f"already indexed: {result.document_id}")
    else:
        print(f"indexed {result.chunk_count} chunks: {result.document_id}")
    return 0


def _search(services: Services, args: argparse.Namespace) -> int:
    config = RetrievalConfig(mode=args.mode, rerank=not args.no_rerank)
    if args.top:
        config = replace(config, final_k=args.top)
    result = services.retriever.search(args.query, config)
    if result.insufficient_evidence:
        print("no sufficient evidence")
    for chunk in result.chunks:
        s = chunk.scores
        print(
            f"{s.final_rank}. [{chunk.section_path}] p{chunk.pages} "
            f"bm25={_rank(s.bm25_rank)} dense={_rank(s.dense_rank)} "
            f"rrf={_score(s.rrf_score)} rerank={_score(s.rerank_score)} "
            f"change={s.rank_change:+d}"
        )
        print(f"   {chunk.text[:200]}")
    for parent in result.parents:
        print(f"parent [{parent.section_path}] chars {parent.char_start}-{parent.char_end}")
    return 0


def main(argv: list[str] | None = None, services: Services | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auditor")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="index a PDF")
    ingest.add_argument("path")
    search = sub.add_parser("search", help="search indexed documents")
    search.add_argument("query")
    search.add_argument("--mode", choices=["bm25", "dense", "hybrid"], default="hybrid")
    search.add_argument("--no-rerank", action="store_true")
    search.add_argument("--top", type=int, default=0)
    args = parser.parse_args(argv)

    services = services or build_services(Settings.from_env())
    if args.command == "ingest":
        return _ingest(services, args.path)
    return _search(services, args)


if __name__ == "__main__":
    raise SystemExit(main())
