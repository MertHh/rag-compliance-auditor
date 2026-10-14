import logging
import threading
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from auditor.api.routes import meta
from auditor.audit.playbook import PlaybookError, PlaybookNotFound
from auditor.config import Settings
from auditor.index.store import InvalidDateError
from auditor.ingestion.indexer import EmptyDocumentError
from auditor.ingestion.parser import InvalidPdfError, ScannedPdfError
from auditor.llm.base import LLMError, ProviderUnavailableError
from auditor.services import Services, build_services
from auditor.storage.db import AuditNotFound, FindingNotFound
from auditor.storage.docstore import DocumentNotFound

log = logging.getLogger(__name__)

STATUS_CODES: dict[type[Exception], int] = {
    DocumentNotFound: 404,
    AuditNotFound: 404,
    FindingNotFound: 404,
    PlaybookNotFound: 404,
    PlaybookError: 422,
    InvalidPdfError: 422,
    ScannedPdfError: 422,
    EmptyDocumentError: 422,
    InvalidDateError: 422,
    ProviderUnavailableError: 503,
    LLMError: 502,
}
_NOT_FOUND_NOUNS = {DocumentNotFound: "document", AuditNotFound: "audit", FindingNotFound: "finding"}


def error_detail(exc: Exception) -> str:
    noun = _NOT_FOUND_NOUNS.get(type(exc))
    if noun is not None:
        return f"{noun} {exc.args[0] if exc.args else ''} not found"
    return str(exc)


def _status_for(exc: Exception) -> int:
    return next(STATUS_CODES[cls] for cls in type(exc).__mro__ if cls in STATUS_CODES)


async def _handle_core_error(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": error_detail(exc)}, status_code=_status_for(exc))


def _warm_up(services: Services) -> None:
    try:
        services.warm_up()
    except Exception:
        log.exception("model warm-up failed; models will load on first use")


def create_app(services: Services | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if services is None:
            load_dotenv()
            app.state.services = build_services(Settings.from_env())
            threading.Thread(target=_warm_up, args=(app.state.services,), daemon=True).start()
        else:
            app.state.services = services
        yield

    app = FastAPI(title="Compliance Auditor API", lifespan=lifespan)
    for exc_type in STATUS_CODES:
        app.add_exception_handler(exc_type, _handle_core_error)
    app.include_router(meta.router)
    return app
