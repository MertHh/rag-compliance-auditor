import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone

from auditor.audit.runner import Auditor, PreparedAudit

log = logging.getLogger(__name__)


@dataclass
class AuditJob:
    audit_id: str
    document_id: str
    playbook: str
    provider: str
    cache_key: str
    status: str  # running | done | failed
    started_at: str
    error: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        del data["cache_key"]
        return data


class AuditJobs:
    """Runs audits on background threads. Jobs live in memory: finished audits are read
    from the database, and a job that was running when the server stopped is gone."""

    def __init__(self, auditor: Auditor, max_workers: int = 2):
        self._auditor = auditor
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="audit")
        self._jobs: dict[str, AuditJob] = {}
        self._lock = threading.Lock()

    def submit(self, prepared: PreparedAudit) -> AuditJob:
        with self._lock:
            for job in self._jobs.values():
                if job.status == "running" and job.cache_key == prepared.cache_key:
                    return replace(job)
            job = AuditJob(
                audit_id=uuid.uuid4().hex,
                document_id=prepared.document_id,
                playbook=prepared.playbook.key,
                provider=prepared.provider.name,
                cache_key=prepared.cache_key,
                status="running",
                started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            self._jobs[job.audit_id] = job
        self._pool.submit(self._run, job.audit_id, prepared)
        return replace(job)

    def _run(self, audit_id: str, prepared: PreparedAudit) -> None:
        try:
            self._auditor.execute(prepared, audit_id)
        except Exception as exc:
            log.exception("audit %s failed", audit_id)
            status, error = "failed", f"{type(exc).__name__}: {exc}"
        else:
            status, error = "done", None
        with self._lock:
            job = self._jobs[audit_id]
            job.status, job.error = status, error

    def get(self, audit_id: str) -> AuditJob | None:
        with self._lock:
            job = self._jobs.get(audit_id)
            return None if job is None else replace(job)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
