from typing import Annotated

from fastapi import Depends, Request

from auditor.api.jobs import AuditJobs
from auditor.services import Services


def get_services(request: Request) -> Services:
    return request.app.state.services


def get_jobs(request: Request) -> AuditJobs:
    return request.app.state.jobs


ServicesDep = Annotated[Services, Depends(get_services)]
JobsDep = Annotated[AuditJobs, Depends(get_jobs)]
