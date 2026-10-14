import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from auditor.audit.graph import build_rule_graph
from auditor.audit.nodes import AuditConfig, RuleNodes, initial_state
from auditor.audit.playbook import LoadedPlaybook, find_playbook
from auditor.audit.prompts import PROMPT_VERSION
from auditor.audit.report import build_finding, build_report
from auditor.audit.trace import TraceRecorder
from auditor.llm.base import LLMProvider, ProviderUnavailableError, models_label
from auditor.retrieval.pipeline import Retriever
from auditor.storage.db import AuditStore
from auditor.storage.docstore import DocumentNotFound, DocumentStore


def config_fingerprint(config: AuditConfig) -> str:
    """Settings that change audit results; concurrency only changes speed."""
    values = asdict(config)
    del values["concurrency"]
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def cache_key(document_id: str, playbook_sha256: str, provider_name: str, model_label: str,
              prompt_version: str = PROMPT_VERSION, settings: str = "") -> str:
    raw = "\n".join([document_id, playbook_sha256, provider_name, model_label, prompt_version,
                     settings])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PreparedAudit:
    document_id: str
    playbook: LoadedPlaybook
    provider: LLMProvider
    cache_key: str


class Auditor:
    def __init__(self, retriever: Retriever, docstore: DocumentStore, audits: AuditStore,
                 playbooks_dir: str | Path, provider_factory: Callable[[str], LLMProvider],
                 config: AuditConfig = AuditConfig()):
        self._retriever = retriever
        self._docstore = docstore
        self._audits = audits
        self._playbooks_dir = Path(playbooks_dir)
        self._providers = provider_factory
        self._config = config

    def prepare(self, document_id: str, playbook_key: str, provider_name: str) -> PreparedAudit:
        """Checks everything that can fail before any model or LLM work starts."""
        if not self._docstore.exists(document_id):
            raise DocumentNotFound(document_id)
        loaded = find_playbook(self._playbooks_dir, playbook_key)
        try:
            provider = self._providers(provider_name)
        except ValueError as exc:  # e.g. an unknown provider or malformed price settings
            raise ProviderUnavailableError(str(exc)) from exc
        provider.check_available()
        key = cache_key(document_id, loaded.sha256, provider.name, models_label(provider),
                        settings=config_fingerprint(self._config))
        return PreparedAudit(document_id, loaded, provider, key)

    def cached(self, prepared: PreparedAudit) -> dict | None:
        report = self._audits.find_cached(prepared.cache_key)
        return None if report is None else {**report, "cached": True}

    def execute(self, prepared: PreparedAudit, audit_id: str | None = None) -> dict:
        recorder = TraceRecorder()
        nodes = RuleNodes(self._retriever, self._docstore, prepared.provider, recorder,
                          prepared.document_id, self._config)
        graph = build_rule_graph(nodes, self._config.max_rewrites)
        rules = prepared.playbook.playbook.rules
        started = time.perf_counter()
        outcomes = graph.batch(
            [initial_state(rule) for rule in rules],
            config={"max_concurrency": self._config.concurrency},
            return_exceptions=True,
        )
        findings = [build_finding(rule, outcome) for rule, outcome in zip(rules, outcomes, strict=True)]
        report = build_report(
            audit_id=audit_id or uuid.uuid4().hex,
            document_id=prepared.document_id,
            playbook_key=prepared.playbook.key,
            provider=prepared.provider,
            findings=findings,
            duration_s=time.perf_counter() - started,
            usage=recorder.totals(),
        )
        self._audits.save_audit(report, recorder.to_dicts(), prepared.cache_key)
        return report

    def run(self, document_id: str, playbook_key: str, provider_name: str, *,
            force: bool = False) -> dict:
        prepared = self.prepare(document_id, playbook_key, provider_name)
        if not force:
            report = self.cached(prepared)
            if report is not None:
                return report
        return self.execute(prepared)
