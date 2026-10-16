"""CUAD v1, the Contract Understanding Atticus Dataset (CC BY 4.0, The Atticus Project):
510 commercial contracts in which lawyers marked the text of 41 clause categories.
The benchmarks use it as an answer key."""

import hashlib
import json
import random
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

CUAD_URL = "https://zenodo.org/records/4595826/files/CUAD_v1.zip"
CUAD_ZIP_MD5 = "c38f490a984420b8a62600db401fafd5"
CUAD_JSON_SHA256 = "ed0b77d85bdf4014d7495800e8e4a70565b48ee6f8a2e5dca9cf8655dbf10eae"
JSON_MEMBER = "CUAD_v1/CUAD_v1.json"

CUAD_CATEGORIES = (
    "Document Name", "Parties", "Agreement Date", "Effective Date", "Expiration Date",
    "Renewal Term", "Notice Period To Terminate Renewal", "Governing Law", "Most Favored Nation",
    "Non-Compete", "Exclusivity", "No-Solicit Of Customers", "Competitive Restriction Exception",
    "No-Solicit Of Employees", "Non-Disparagement", "Termination For Convenience",
    "Rofr/Rofo/Rofn", "Change Of Control", "Anti-Assignment", "Revenue/Profit Sharing",
    "Price Restrictions", "Minimum Commitment", "Volume Restriction", "Ip Ownership Assignment",
    "Joint Ip Ownership", "License Grant", "Non-Transferable License",
    "Affiliate License-Licensor", "Affiliate License-Licensee",
    "Unlimited/All-You-Can-Eat-License", "Irrevocable Or Perpetual License", "Source Code Escrow",
    "Post-Termination Services", "Audit Rights", "Uncapped Liability", "Cap On Liability",
    "Liquidated Damages", "Warranty Duration", "Insurance", "Covenant Not To Sue",
    "Third Party Beneficiary",
)
# Facts about the contract rather than clauses to look for.
METADATA_CATEGORIES = frozenset(
    {"Document Name", "Parties", "Agreement Date", "Effective Date", "Expiration Date"}
)

Span = tuple[int, int]
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class CuadContract:
    title: str
    text: str
    spans: dict[str, list[Span]]  # category -> expert-marked spans; empty when the clause is absent


def _details(question: str) -> str:
    _, _, details = question.partition("Details:")
    return _SPACES.sub(" ", details).strip()


def load_cuad(path: str | Path) -> tuple[list[CuadContract], dict[str, str]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    contracts: list[CuadContract] = []
    details: dict[str, str] = {}
    for entry in raw["data"]:
        paragraph = entry["paragraphs"][0]
        spans: dict[str, list[Span]] = {}
        for qa in paragraph["qas"]:
            category = qa["id"].split("__", 1)[1]
            details.setdefault(category, _details(qa["question"]))
            spans[category] = sorted({(a["answer_start"], a["answer_start"] + len(a["text"]))
                                      for a in qa["answers"]})
        contracts.append(CuadContract(entry["title"], paragraph["context"], spans))
    return contracts, details


def clause_categories(details: dict[str, str]) -> list[str]:
    return sorted(c for c in details if c not in METADATA_CATEGORIES)


def query_for(category: str, details: dict[str, str]) -> str:
    return f"{category}: {details[category]}"


def select_subset(contracts: list[CuadContract], n: int, seed: int = 13) -> list[str]:
    titles = sorted(c.title for c in contracts)
    if n > len(titles):
        raise ValueError(f"subset of {n} asked from {len(titles)} contracts")
    return sorted(random.Random(seed).sample(titles, n))


def save_subset(path: str | Path, titles: list[str]) -> None:
    Path(path).write_text(json.dumps(titles, indent=2) + "\n", encoding="utf-8")


def load_subset(path: str | Path) -> list[str]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download_cuad(dest: str | Path, *, url: str = CUAD_URL, zip_md5: str = CUAD_ZIP_MD5,
                  json_sha256: str = CUAD_JSON_SHA256) -> Path:
    """Downloads the CUAD zip, checks it, and keeps only CUAD_v1.json."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "CUAD_v1.json"
    if target.exists() and _digest(target, "sha256") == json_sha256:
        return target
    archive = dest / "CUAD_v1.zip"
    urllib.request.urlretrieve(url, archive)
    try:
        if _digest(archive, "md5") != zip_md5:
            raise ValueError(f"{archive.name}: checksum mismatch; the download is incomplete or changed")
        with zipfile.ZipFile(archive) as zf:
            data = zf.read(JSON_MEMBER)
    finally:
        archive.unlink(missing_ok=True)
    if hashlib.sha256(data).hexdigest() != json_sha256:
        raise ValueError(f"{JSON_MEMBER}: checksum mismatch")
    target.write_bytes(data)
    return target
