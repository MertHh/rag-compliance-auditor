from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from auditor.api.routes.deps import ServicesDep
from auditor.api.schemas import Filters, ProviderName
from auditor.qa.answer import QuestionAnswerer
from auditor.retrieval.config import RetrievalConfig

router = APIRouter(tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["bm25", "dense", "hybrid"] = "hybrid"
    rerank: bool = True
    final_k: int = Field(5, ge=1, le=30)
    filters: Filters = Field(default_factory=Filters)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    filters: Filters = Field(default_factory=Filters)
    provider: ProviderName | None = None


@router.post("/search")
def search(body: SearchRequest, services: ServicesDep) -> dict:
    config = RetrievalConfig(mode=body.mode, rerank=body.rerank, final_k=body.final_k)
    result = services.retriever.search(body.query, config, body.filters.to_filter())
    return {
        "query": result.query,
        "config": asdict(result.config),
        "insufficient_evidence": result.insufficient_evidence,
        "chunks": [asdict(chunk) for chunk in result.chunks],
        "parents": [asdict(parent) for parent in result.parents],
    }


@router.post("/ask")
def ask(body: AskRequest, services: ServicesDep) -> dict:
    provider = services.provider(body.provider or services.default_provider)
    provider.check_available()
    answer = QuestionAnswerer(services.retriever, services.docstore, provider).ask(
        body.question, body.filters.to_filter()
    )
    return {
        "question": answer.question,
        "found": answer.found,
        "answer": answer.answer,
        "message": answer.message,
        "citations": [citation.to_dict() for citation in answer.citations],
        "passages": [asdict(passage) for passage in answer.passages],
        "model": answer.model,
        "usage": asdict(answer.usage),
    }
