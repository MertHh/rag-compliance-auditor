import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

RuleType = Literal["must_exist", "must_not_exist", "condition"]
Severity = Literal["low", "medium", "high"]

_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


class PlaybookError(Exception):
    pass


class PlaybookNotFound(PlaybookError):
    pass


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1)
    type: RuleType
    severity: Severity
    queries: list[str] = Field(min_length=1)
    criteria: str = Field(min_length=1)

    @field_validator("queries")
    @classmethod
    def _no_blank_queries(cls, value: list[str]) -> list[str]:
        if any(not query.strip() for query in value):
            raise ValueError("queries must not contain blank entries")
        return value


class Playbook(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    rules: list[Rule] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> "Playbook":
        seen: set[str] = set()
        for rule in self.rules:
            if rule.id in seen:
                raise ValueError(f"duplicate rule id {rule.id!r}")
            seen.add(rule.id)
        return self


@dataclass(frozen=True)
class LoadedPlaybook:
    key: str
    playbook: Playbook
    sha256: str


def _describe(raw: dict, error: dict) -> str:
    loc = error["loc"]
    if len(loc) >= 2 and loc[0] == "rules" and isinstance(loc[1], int):
        rules = raw.get("rules")
        entry = rules[loc[1]] if isinstance(rules, list) and loc[1] < len(rules) else None
        rule_id = entry.get("id") if isinstance(entry, dict) else None
        where = f"rule {rule_id!r} (rules[{loc[1]}])" if rule_id else f"rules[{loc[1]}]"
        field = ".".join(str(part) for part in loc[2:]) or "(rule)"
        return f"{where}: field {field!r}: {error['msg']}"
    field = ".".join(str(part) for part in loc) or "(playbook)"
    return f"field {field!r}: {error['msg']}"


def load_playbook(path: str | Path) -> LoadedPlaybook:
    path = Path(path)
    data = path.read_bytes()
    try:
        raw = yaml.safe_load(data)
    except yaml.YAMLError as exc:
        raise PlaybookError(f"{path.name}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise PlaybookError(f"{path.name}: playbook must be a mapping with 'name' and 'rules'")
    try:
        playbook = Playbook.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(_describe(raw, error) for error in exc.errors())
        raise PlaybookError(f"{path.name}: {details}") from exc
    # Line endings are normalized so a checkout or an editor that rewrites them keeps the audit cache.
    return LoadedPlaybook(path.stem, playbook, hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest())


def list_playbooks(directory: str | Path) -> list[str]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.yaml"))


def find_playbook(directory: str | Path, key: str) -> LoadedPlaybook:
    path = Path(directory) / f"{key}.yaml"
    if not _KEY.match(key) or not path.is_file():
        available = ", ".join(list_playbooks(directory)) or "none"
        raise PlaybookNotFound(f"playbook {key!r} not found; available: {available}")
    return load_playbook(path)
