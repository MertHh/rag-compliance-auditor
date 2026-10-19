from dataclasses import dataclass

from pydantic import BaseModel

from auditor.audit.citations import Citation, verify_quotes
from auditor.audit.prompts import format_sections
from auditor.index.store import SearchFilter
from auditor.llm.base import LLMProvider, Usage, complete_with_retry
from auditor.retrieval.config import RetrievalConfig
from auditor.retrieval.pipeline import ParentPassage, Retriever
from auditor.storage.docstore import DocumentStore

NOT_FOUND_MESSAGE = "I could not find a statement about this in these documents."

QA_SYSTEM = (
    "You answer questions about documents using only the numbered sections you receive. "
    "Answer in one to three sentences. Copy the sentences that support the answer into quotes "
    "word for word, without changing, joining or shortening them. If the sections do not answer "
    "the question, return an empty answer and no quotes."
)


class QAOutput(BaseModel):
    answer: str
    quotes: list[str]


@dataclass
class Answer:
    question: str
    found: bool
    answer: str | None
    message: str | None
    citations: list[Citation]
    passages: list[ParentPassage]
    model: str | None
    usage: Usage


def qa_prompt(question: str, passages: list[ParentPassage]) -> str:
    return f"Question: {question}\n\nSections:\n\n{format_sections(passages)}"


class QuestionAnswerer:
    def __init__(self, retriever: Retriever, docstore: DocumentStore, provider: LLMProvider,
                 config: RetrievalConfig | None = None):
        self._retriever = retriever
        self._docstore = docstore
        self._provider = provider
        self._config = config or RetrievalConfig()

    def ask(self, question: str, flt: SearchFilter | None = None) -> Answer:
        result = self._retriever.search(question, self._config, flt)
        if result.insufficient_evidence:
            return Answer(question, False, None, NOT_FOUND_MESSAGE, [], result.parents, None, Usage())

        llm = complete_with_retry(self._provider, QA_SYSTEM, qa_prompt(question, result.parents),
                                  QAOutput, "small")
        citations: list[Citation] = []
        for document_id in dict.fromkeys(p.document_id for p in result.parents):
            doc = self._docstore.load(document_id)
            citations.extend(verify_quotes(doc, llm.value.quotes, result.parents))
        text = llm.value.answer.strip()
        if not text or not citations:
            return Answer(question, False, None, NOT_FOUND_MESSAGE, [], result.parents,
                          llm.model, llm.usage)
        return Answer(question, True, text, None, citations, result.parents, llm.model, llm.usage)
