import argparse
import json
import sys
from dataclasses import replace

from dotenv import load_dotenv

from auditor.audit.playbook import PlaybookError
from auditor.config import Settings
from auditor.index.store import SearchFilter
from auditor.ingestion.indexer import EmptyDocumentError
from auditor.ingestion.metadata import MetadataExtractor
from auditor.ingestion.parser import InvalidPdfError, ScannedPdfError
from auditor.llm.base import LLMError, LLMProvider, ProviderUnavailableError
from auditor.llm.factory import PROVIDERS
from auditor.qa.answer import QuestionAnswerer
from auditor.retrieval.config import RetrievalConfig
from auditor.services import Services, build_services
from auditor.storage.docstore import DocumentNotFound


def _rank(rank: int | None) -> str:
    return f"#{rank}" if rank is not None else "-"


def _score(score: float | None) -> str:
    return f"{score:.3f}" if score is not None else "-"


def _provider(services: Services, name: str | None) -> LLMProvider:
    provider = services.provider(name or services.default_provider)
    provider.check_available()
    return provider


def _citation_line(citation: dict) -> str:
    page = f"p{citation['page']}" if citation["page"] is not None else "p-"
    return f'   "{citation["quote"][:160]}" ({page}, {citation["section_path"] or "-"})'


def _ingest(services: Services, args: argparse.Namespace) -> int:
    extractor = None
    if not args.no_metadata:
        try:
            extractor = MetadataExtractor(_provider(services, args.provider))
        except (ProviderUnavailableError, ValueError) as exc:
            print(f"warning: metadata extraction skipped: {exc}", file=sys.stderr)
    try:
        result = services.indexer.ingest_pdf(args.path, extract_metadata=extractor)
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


def _ask(services: Services, args: argparse.Namespace) -> int:
    flt = SearchFilter(document_ids=args.document) if args.document else None
    try:
        answerer = QuestionAnswerer(services.retriever, services.docstore,
                                    _provider(services, args.provider))
        answer = answerer.ask(args.question, flt)
    except (ProviderUnavailableError, LLMError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not answer.found:
        print(answer.message)
        for passage in answer.passages:
            print(f"   nearest: [{passage.section_path}] {passage.text[:120]}")
        return 0
    print(answer.answer)
    for citation in answer.citations:
        print(_citation_line(citation.to_dict()))
    return 0


def _audit(services: Services, args: argparse.Namespace) -> int:
    try:
        report = services.auditor.run(args.document_id, args.playbook,
                                      args.provider or services.default_provider, force=args.force)
    except DocumentNotFound:
        print(f"error: document {args.document_id} is not indexed", file=sys.stderr)
        return 1
    except (PlaybookError, ProviderUnavailableError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    risk = "-" if report["risk_score"] is None else f"{report['risk_score']:.1f}"
    cached = " (cached)" if report["cached"] else ""
    print(f"audit {report['audit_id']}  risk {risk}  model {report['model']}{cached}")
    for finding in report["findings"]:
        evidence = finding["evidence"]
        print(f"{finding['status']:<9} {finding['severity']:<6} {finding['rule_id']}  "
              f"citations={len(finding['citations'])} queries={evidence['queries_tried']} "
              f"sections={evidence['sections_examined']}")
        if finding["error"]:
            print(f"   error: {finding['error']}")
        for citation in finding["citations"][:2]:
            print(_citation_line(citation))
    totals = report["totals"]
    print(f"duration {totals['duration_s']}s  tokens {totals['input_tokens']}/"
          f"{totals['output_tokens']}  cost ${totals['cost_usd']:.4f}")
    return 0


def main(argv: list[str] | None = None, services: Services | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auditor")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="index a PDF")
    ingest.add_argument("path")
    ingest.add_argument("--provider", choices=PROVIDERS)
    ingest.add_argument("--no-metadata", action="store_true")

    search = sub.add_parser("search", help="search indexed documents")
    search.add_argument("query")
    search.add_argument("--mode", choices=["bm25", "dense", "hybrid"], default="hybrid")
    search.add_argument("--no-rerank", action="store_true")
    search.add_argument("--top", type=int, default=0)

    ask = sub.add_parser("ask", help="answer a question with quotes")
    ask.add_argument("question")
    ask.add_argument("--document", action="append")
    ask.add_argument("--provider", choices=PROVIDERS)

    audit = sub.add_parser("audit", help="audit a document against a playbook")
    audit.add_argument("document_id")
    audit.add_argument("playbook")
    audit.add_argument("--provider", choices=PROVIDERS)
    audit.add_argument("--force", action="store_true")
    audit.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if services is None:
        load_dotenv()
        services = build_services(Settings.from_env())
    handlers = {"ingest": _ingest, "search": _search, "ask": _ask, "audit": _audit}
    return handlers[args.command](services, args)


if __name__ == "__main__":
    raise SystemExit(main())
