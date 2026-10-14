import json
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from auditor.api.routes.deps import JobsDep, ServicesDep
from auditor.api.schemas import ProviderName
from auditor.audit.export import report_pdf
from auditor.storage.db import AuditNotFound

router = APIRouter(prefix="/audits", tags=["audits"])


class AuditRequest(BaseModel):
    document_id: str
    playbook: str
    provider: ProviderName | None = None
    force: bool = False


class ReviewRequest(BaseModel):
    decision: Literal["accepted", "rejected"]
    note: str = Field("", max_length=2000)


@router.post("")
def start_audit(body: AuditRequest, response: Response, services: ServicesDep,
                jobs: JobsDep) -> dict:
    prepared = services.auditor.prepare(body.document_id, body.playbook,
                                        body.provider or services.default_provider)
    if not body.force:
        report = services.auditor.cached(prepared)
        if report is not None:
            return report
    response.status_code = 202
    return jobs.submit(prepared).to_dict()


@router.get("")
def list_audits(services: ServicesDep, document_id: str | None = None) -> list[dict]:
    return services.audits.list_audits(document_id)


@router.get("/{audit_id}")
def get_audit(audit_id: str, response: Response, services: ServicesDep, jobs: JobsDep) -> dict:
    report = services.audits.get_report(audit_id)
    if report is not None:
        return report
    job = jobs.get(audit_id)
    if job is None:
        raise AuditNotFound(audit_id)
    if job.status == "failed":
        raise HTTPException(500, f"audit failed: {job.error}")
    response.status_code = 202
    return job.to_dict()


@router.get("/{audit_id}/trace")
def get_trace(audit_id: str, services: ServicesDep, jobs: JobsDep) -> list[dict]:
    trace = services.audits.get_trace(audit_id)
    if trace is not None:
        return trace
    job = jobs.get(audit_id)
    if job is not None and job.status == "running":
        raise HTTPException(409, "audit is still running")
    raise AuditNotFound(audit_id)


@router.post("/{audit_id}/findings/{rule_id}/review")
def review_finding(audit_id: str, rule_id: str, body: ReviewRequest,
                   services: ServicesDep) -> dict:
    return services.audits.set_review(audit_id, rule_id, body.decision, body.note)


@router.get("/{audit_id}/export")
def export_audit(audit_id: str, services: ServicesDep,
                 fmt: Annotated[Literal["json", "pdf"], Query(alias="format")] = "json") -> Response:
    report = services.audits.get_report(audit_id)
    if report is None:
        raise AuditNotFound(audit_id)
    headers = {"Content-Disposition": f'attachment; filename="audit-{audit_id}.{fmt}"'}
    if fmt == "json":
        body = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(body, media_type="application/json", headers=headers)
    pdf = report_pdf(report, services.docstore.pdf_path(report["document_id"]))
    return Response(pdf, media_type="application/pdf", headers=headers)
