"""A three-contract file in CUAD's SQuAD format, for benchmark tests."""

import json
from pathlib import Path

QUESTION = ('Highlight the parts (if any) of this contract related to "{0}" that should be '
            'reviewed by a lawyer. Details: {1}')
DETAILS = {
    "Document Name": "The name of the contract",
    "Cap On Liability": "Does the contract include a cap on liability upon the breach of a party’s obligation?",
    "Governing Law": "Which state/country's law governs the interpretation of the contract?",
}
CAP = "The total liability of either party shall not exceed the fees paid in the twelve months before the claim."
LAW = "This Agreement is governed by the laws of the State of New York."

CONTRACTS = {
    "ALPHA-SUPPLY": ("SUPPLY AGREEMENT\n\n1. Definitions\nProducts means the goods listed in Exhibit A.\n\n"
                     f"2. Limitation of Liability\n{CAP}\n\n3. Governing Law\n{LAW}\n"),
    "BETA-SERVICES": ("SERVICES AGREEMENT\n\n1. Services\nThe provider performs the services in Exhibit B.\n\n"
                      f"2. Governing Law\n{LAW}\n\n3. Payment\nFees are due within thirty days of invoice.\n"),
    "GAMMA-LICENSE": ("LICENSE AGREEMENT\n\n1. License\nLicensor grants a non-exclusive license to use the software.\n\n"
                      f"2. Liability\n{CAP}\n\n3. Term\nThis agreement lasts two years.\n"),
}


def _answers(text: str, needle: str) -> list[dict]:
    return [{"text": needle, "answer_start": text.index(needle)}] if needle in text else []


def write_cuad(path: Path) -> Path:
    data = []
    for title, text in CONTRACTS.items():
        needles = {"Document Name": text.split("\n", 1)[0], "Cap On Liability": CAP, "Governing Law": LAW}
        qas = []
        for category, needle in needles.items():
            answers = _answers(text, needle)
            qas.append({"id": f"{title}__{category}", "question": QUESTION.format(category, DETAILS[category]),
                        "answers": answers, "is_impossible": not answers})
        data.append({"title": title, "paragraphs": [{"context": text, "qas": qas}]})
    path.write_text(json.dumps({"version": "aok_v1.0", "data": data}), encoding="utf-8")
    return path
