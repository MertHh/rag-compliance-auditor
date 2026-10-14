from pydantic import BaseModel

from auditor.audit.playbook import Rule
from auditor.retrieval.pipeline import ParentPassage

# Bump on any change to the prompt text or the schemas: it is part of the audit cache key.
PROMPT_VERSION = "1"


class Evaluation(BaseModel):
    clause_found: bool
    matches_criteria: bool
    reasoning: str
    quotes: list[str]


class RewrittenQueries(BaseModel):
    queries: list[str]


class Relevance(BaseModel):
    relevant: bool


RULE_KIND = {
    "must_exist": "The contract must contain this clause.",
    "must_not_exist": "The contract must NOT contain this clause; it is prohibited.",
    "condition": "If the contract has this clause, the clause must meet the criteria.",
}

EVALUATE_SYSTEM = (
    "You review contracts against compliance rules. You receive one rule and numbered sections "
    "from a single contract. Set clause_found to true if the sections contain a clause on the "
    "rule's topic. Set matches_criteria to true if that clause matches the rule's criteria. When "
    "the rule says the clause is prohibited, the criteria describe the prohibited clause, and "
    "matches_criteria means the text is that prohibited clause. Copy the decisive sentences into "
    "quotes word for word from the sections, without changing, joining or shortening them. If "
    "clause_found is false, return no quotes and set matches_criteria to false. Explain the "
    "decision in reasoning in two or three sentences."
)

REWRITE_SYSTEM = (
    "You write search queries for finding a clause in a contract. Return two or three short "
    "queries worded differently from the queries that already failed, using synonyms and the "
    "terms contracts commonly use for this clause."
)

RELEVANCE_SYSTEM = (
    "You check whether one contract section is relevant to a compliance rule. Set relevant to "
    "true only if the section contains a clause on the rule's topic, whether or not the clause "
    "meets the criteria."
)


def format_sections(passages: list[ParentPassage]) -> str:
    return "\n\n".join(
        f"[Section {i}: {p.section_path or 'untitled'}]\n{p.text}"
        for i, p in enumerate(passages, start=1)
    )


def rule_block(rule: Rule) -> str:
    return f"Rule: {rule.title}\nKind: {RULE_KIND[rule.type]}\nCriteria: {rule.criteria}"


def evaluate_prompt(rule: Rule, passages: list[ParentPassage]) -> str:
    return f"{rule_block(rule)}\n\nSections:\n\n{format_sections(passages)}"


def rewrite_prompt(rule: Rule, tried: list[str]) -> str:
    tried_lines = "\n".join(f"- {query}" for query in tried)
    return f"{rule_block(rule)}\n\nQueries that found nothing relevant:\n{tried_lines}"


def relevance_prompt(rule: Rule, passage: ParentPassage) -> str:
    return f"{rule_block(rule)}\n\n{format_sections([passage])}"
