from fakes import FakeLLM

from auditor.ingestion.chunker import build_chunks
from auditor.ingestion.context import ContextLine, LLMContextualizer
from auditor.ingestion.parser import parse_text
from auditor.ingestion.structure import detect_sections
from auditor.llm.base import LLMError

SENTENCE = " A services agreement between Acme Corp and Beta LLC; this passage caps liability. "


def _doc_and_chunk(sample_contract):
    doc = parse_text(sample_contract, "msa.txt")
    chunks = build_chunks(doc, detect_sections(doc.lines))
    return doc, next(c for c in chunks if "aggregate liability" in c.text)


def test_returns_one_stripped_sentence_and_counts_usage(sample_contract):
    llm = FakeLLM({"ContextLine": ContextLine(sentence=SENTENCE)})
    contextualizer = LLMContextualizer(lambda: llm)
    doc, chunk = _doc_and_chunk(sample_contract)
    assert contextualizer(doc, chunk) == SENTENCE.strip()
    contextualizer(doc, chunk)
    assert contextualizer.usage.input_tokens == 200
    [(schema, tier, prompt), _] = llm.calls
    assert (schema, tier) == ("ContextLine", "small")
    assert prompt.startswith("Contract opening:\nMASTER SERVICES AGREEMENT")
    assert prompt.index("Contract opening:") < prompt.index(f"Passage (section {chunk.section_path}):")
    assert prompt.endswith(chunk.text)


def test_failure_gives_empty_prefix(sample_contract):
    contextualizer = LLMContextualizer(lambda: FakeLLM({"ContextLine": LLMError("schema")}))
    doc, chunk = _doc_and_chunk(sample_contract)
    assert contextualizer(doc, chunk) == ""
    assert contextualizer.failures == 1
    assert contextualizer.usage.input_tokens == 0
