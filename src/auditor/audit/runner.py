import hashlib
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from auditor.audit.graph import build_rule_graph
from auditor.audit.nodes import AuditConfig, RuleNodes, initial_state
from auditor.audit.playbook import find_playbook
from auditor.audit.prompts import PROMPT_VERSION
from auditor.audit.report import build_finding, build_report
from auditor.audit.trace import TraceRecorder
from auditor.llm.base import LLMProvider, models_label
from auditor.retrieval.pipeline import Retriever
from auditor.storage.db import AuditStore
from auditor.storage.docstore import DocumentNotFound, DocumentStore


def cache_key(document_id: str, playbook_sha256: str, provider_name: str, model_label: str,
              prompt_version: str = PROMPT_VERSION) -> str:
    raw = "\n".join([document_id, playbook_sha256, provider_name, model_label, prompt_version])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
        # Retrieval touches the vector store and GPU models, which are not thread-safe.
        self._lock = threading.Lock()

    def run(self, document_id: str, playbook_key: str, provider_name: str, *,
            force: bool = False) -> dict:
        if not self._docstore.exists(document_id):
            raise DocumentNotFound(document_id)
        loaded = find_playbook(self._playbooks_dir, playbook_key)
        provider = self._providers(provider_name)
        provider.check_available()

        key = cache_key(document_id, loaded.sha256, provider.name, models_label(provider))
        if not force:
            cached = self._audits.find_cached(key)
            if cached is not None:
                return {**cached, "cached": True}

        recorder = TraceRecorder()
        nodes = RuleNodes(self._retriever, self._docstore, provider, recorder, document_id,
                          self._config, self._lock)
        graph = build_rule_graph(nodes, self._config.max_rewrites)
        rules = loaded.playbook.rules
        started = time.perf_counter()
        outcomes = graph.batch(
            [initial_state(rule) for rule in rules],
            config={"max_concurrency": self._config.concurrency},
            return_exceptions=True,
        )
        findings = [build_finding(rule, outcome) for rule, outcome in zip(rules, outcomes, strict=True)]
        report = build_report(
            audit_id=uuid.uuid4().hex,
            document_id=document_id,
            playbook_key=loaded.key,
            provider=provider,
            findings=findings,
            duration_s=time.perf_counter() - started,
            usage=recorder.totals(),
        )
        self._audits.save_audit(report, recorder.to_dicts(), key)
        return report
