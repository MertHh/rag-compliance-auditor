import re
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from auditor.api.routes.deps import ServicesDep
from auditor.api.schemas import ProviderName
from auditor.ingestion.metadata import MetadataExtractor
from auditor.llm.base import ProviderUnavailableError
from auditor.services import Services
from auditor.storage.docstore import DocumentNotFound

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_UNSAFE_CHARS = re.compile(r'[<>:"/\|?*\x00-\x1f]')


def safe_filename(name: str | None) -> str:
    """Keeps only the last path component and replaces characters Windows rejects."""
    base = re.split(r"[\\/]", name or "")[-1]
    cleaned = _UNSAFE_CHARS.sub("_", base).strip(" .")
    if not cleaned:
        return "upload.pdf"
    path = Path(cleaned)
    return path.stem[:150] + path.suffix[:4] if len(cleaned) > 154 else cleaned


def summary(services: Services, document_id: str) -> dict:
    meta = services.docstore.metadata(document_id)
    return {
        "document_id": document_id,
        "filename": meta.get("filename"),
        "doc_type": meta.get("doc_type"),
        "date": meta.get("date"),
        "parties": meta.get("parties", []),
        "jurisdiction": meta.get("jurisdiction"),
        "has_pdf": services.docstore.pdf_path(document_id) is not None,
        "indexed": services.indexer.is_indexed(document_id),
    }


@router.get("")
def list_documents(services: ServicesDep) -> list[dict]:
    return [summary(services, document_id) for document_id in services.docstore.list_ids()]


@router.get("/{document_id}")
def get_document(document_id: str, services: ServicesDep) -> dict:
    return summary(services, document_id)


@router.get("/{document_id}/file")
def get_file(document_id: str, services: ServicesDep) -> FileResponse:
    if not services.docstore.exists(document_id):
        raise DocumentNotFound(document_id)
    path = services.docstore.pdf_path(document_id)
    if path is None:
        raise HTTPException(404, "document has no PDF")
    return FileResponse(path, media_type="application/pdf",
                        filename=services.docstore.metadata(document_id).get("filename") or path.name)


@router.post("")
def upload(
    services: ServicesDep,
    file: Annotated[UploadFile, File()],
    doc_type: Annotated[str | None, Form()] = None,
    date: Annotated[str | None, Form()] = None,
    jurisdiction: Annotated[str | None, Form()] = None,
    parties: Annotated[list[str] | None, Form()] = None,
    extract_metadata: Annotated[bool, Form()] = True,
    provider: Annotated[ProviderName | None, Form()] = None,
) -> dict:
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file is larger than 50 MB")

    given = {
        "doc_type": (doc_type or "").strip() or None,
        "date": (date or "").strip() or None,
        "jurisdiction": (jurisdiction or "").strip() or None,
        "parties": [p.strip() for p in parties or [] if p.strip()] or None,
    }
    warnings: list[str] = []
    extractor = None
    if extract_metadata:
        try:
            llm = services.provider(provider or services.default_provider)
            llm.check_available()
            extractor = MetadataExtractor(llm)
        except (ProviderUnavailableError, ValueError) as exc:
            warnings.append(f"metadata extraction skipped: {exc}")

    # parse_pdf names the document after the file, so keep the uploaded name.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / safe_filename(file.filename)
        path.write_bytes(data)
        result = services.indexer.ingest_pdf(path, given, extract_metadata=extractor)
    return {
        "document_id": result.document_id,
        "chunk_count": result.chunk_count,
        "already_indexed": result.already_indexed,
        "warnings": warnings,
        "document": summary(services, result.document_id),
    }
