from dataclasses import dataclass

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


@dataclass(frozen=True)
class Wording:
    """The nouns the prompts use for the reviewed text and for what one rule looks for, both
    singular; a playbook sets them. "contract" and "clause" give the benchmarked prompts."""

    document: str = "document"
    item: str = "passage"

    def kind(self, rule_type: str) -> str:
        d, i = self.document, self.item
        return {
            "must_exist": f"The {d} must contain this {i}.",
            "must_not_exist": f"The {d} must NOT contain this {i}; it is prohibited.",
            "condition": f"If the {d} has this {i}, the {i} must meet the criteria.",
        }[rule_type]

    def evaluate_system(self) -> str:
        d, i = self.document, self.item
        return (
            f"You review {d}s against compliance rules. You receive one rule and numbered sections "
            f"from a single {d}. Set clause_found to true if the sections contain a {i} on the "
            f"rule's topic. Set matches_criteria to true if that {i} matches the rule's criteria. When "
            f"the rule says the {i} is prohibited, the criteria describe the prohibited {i}, and "
            f"matches_criteria means the text is that prohibited {i}. Copy the decisive sentences into "
            "quotes word for word from the sections, without changing, joining or shortening them. If "
            "clause_found is false, return no quotes and set matches_criteria to false. Explain the "
            "decision in reasoning in two or three sentences."
        )

    def rewrite_system(self) -> str:
        d, i = self.document, self.item
        return (
            f"You write search queries for finding a {i} in a {d}. Return two or three short "
            "queries worded differently from the queries that already failed, using synonyms and the "
            f"terms {d}s commonly use for this {i}."
        )

    def relevance_system(self) -> str:
        d, i = self.document, self.item
        return (
            f"You check whether one {d} section is relevant to a compliance rule. Set relevant to "
            f"true only if the section contains a {i} on the rule's topic, whether or not the {i} "
            "meets the criteria."
        )


def format_sections(passages: list[ParentPassage]) -> str:
    return "\n\n".join(
        f"[Section {i}: {p.section_path or 'untitled'}]\n{p.text}"
        for i, p in enumerate(passages, start=1)
    )


def rule_block(rule: Rule, wording: Wording = Wording()) -> str:
    return f"Rule: {rule.title}\nKind: {wording.kind(rule.type)}\nCriteria: {rule.criteria}"


def evaluate_prompt(rule: Rule, passages: list[ParentPassage], wording: Wording = Wording()) -> str:
    return f"{rule_block(rule, wording)}\n\nSections:\n\n{format_sections(passages)}"


def rewrite_prompt(rule: Rule, tried: list[str], wording: Wording = Wording()) -> str:
    tried_lines = "\n".join(f"- {query}" for query in tried)
    return f"{rule_block(rule, wording)}\n\nQueries that found nothing relevant:\n{tried_lines}"


def relevance_prompt(rule: Rule, passage: ParentPassage, wording: Wording = Wording()) -> str:
    return f"{rule_block(rule, wording)}\n\n{format_sections([passage])}"
