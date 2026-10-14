from fakes import FakeLLM, audit_llm, fake_services
from fastapi.testclient import TestClient

from auditor.api.main import create_app
from auditor.api.routes.documents import MAX_UPLOAD_BYTES, safe_filename


def _upload(client, path, **form):
    with open(path, "rb") as fh:
        return client.post("/documents", files={"file": (path.name, fh, "application/pdf")},
                           data=form)


def test_upload_indexes_and_extracts_metadata(api, contract_pdf):
    response = _upload(api, contract_pdf)
    assert response.status_code == 200
    body = response.json()
    assert body["already_indexed"] is False and body["chunk_count"] == 2
    assert body["warnings"] == []
    doc = body["document"]
    assert doc["filename"] == "contract.pdf"
    assert doc["doc_type"] == "Services Agreement"
    assert doc["has_pdf"] is True and doc["indexed"] is True

    again = _upload(api, contract_pdf).json()
    assert again["already_indexed"] is True
    assert again["document_id"] == body["document_id"]


def test_user_metadata_overrides_extracted_and_blank_fields_do_not(api, contract_pdf):
    body = _upload(api, contract_pdf, jurisdiction="Delaware", doc_type="",
                   parties=["Acme Corp", "Beta LLC"]).json()
    doc = body["document"]
    assert doc["jurisdiction"] == "Delaware"
    assert doc["doc_type"] == "Services Agreement"
    assert doc["parties"] == ["Acme Corp", "Beta LLC"]


def test_upload_without_extraction_skips_llm(api, api_llm, contract_pdf):
    body = _upload(api, contract_pdf, extract_metadata="false").json()
    assert body["document"]["doc_type"] is None
    assert api_llm.calls == []


def test_unavailable_provider_indexes_with_warning(tmp_path, playbooks_dir, contract_pdf):
    services = fake_services(tmp_path, playbooks_dir, FakeLLM(unavailable="OPENAI_API_KEY is not set"))
    with TestClient(create_app(services)) as client:
        body = _upload(client, contract_pdf).json()
    assert body["chunk_count"] == 2
    assert body["warnings"] == ["metadata extraction skipped: OPENAI_API_KEY is not set"]


def test_list_get_and_download(api, contract_pdf):
    document_id = _upload(api, contract_pdf).json()["document_id"]
    [listed] = api.get("/documents").json()
    assert listed["document_id"] == document_id
    assert api.get(f"/documents/{document_id}").json() == listed
    pdf = api.get(f"/documents/{document_id}/file")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content == contract_pdf.read_bytes()


def test_text_only_document_has_no_file(api, api_services, sample_contract):
    document_id = api_services.indexer.ingest_text(sample_contract, "c.txt").document_id
    response = api.get(f"/documents/{document_id}/file")
    assert response.status_code == 404
    assert response.json() == {"detail": "document has no PDF"}


def test_unknown_or_unsafe_ids_are_404(api):
    for bad in ["0" * 64, "..\\..\\secret", "a:b"]:
        assert api.get(f"/documents/{bad}").status_code == 404
        assert api.get(f"/documents/{bad}/file").status_code == 404


def test_bad_uploads_get_clear_errors(api, tmp_path, make_pdf):
    text = tmp_path / "notes.pdf"
    text.write_bytes(b"just text, not a pdf")
    response = _upload(api, text)
    assert response.status_code == 422 and response.json()["detail"]

    scanned = make_pdf(tmp_path / "scan.pdf", [[]])
    response = _upload(api, scanned)
    assert response.status_code == 422 and "scanned" in response.json()["detail"]

    big = api.post("/documents", files={"file": ("big.pdf", b"0" * (MAX_UPLOAD_BYTES + 1),
                                                 "application/pdf")})
    assert big.status_code == 413
    assert big.json() == {"detail": "file is larger than 50 MB"}


def test_odd_filenames_are_cleaned(api, contract_pdf):
    with open(contract_pdf, "rb") as fh:
        body = api.post("/documents", files={"file": ("C:\\fake\\a:b?.pdf", fh, "application/pdf")}).json()
    assert body["document"]["filename"] == "a_b_.pdf"


def test_safe_filename():
    assert safe_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert safe_filename("C:\\Users\\x\\My Contract.pdf") == "My Contract.pdf"
    assert safe_filename('a<b>"c|d*.pdf') == "a_b__c_d_.pdf"
    assert safe_filename("") == "upload.pdf"
    assert safe_filename(None) == "upload.pdf"
    assert safe_filename("...") == "upload.pdf"
    long = safe_filename("x" * 300 + ".pdf")
    assert len(long) <= 154 and long.endswith(".pdf")


def test_very_long_filename_is_accepted(api, contract_pdf):
    with open(contract_pdf, "rb") as fh:
        response = api.post("/documents", files={"file": ("x" * 300 + ".pdf", fh, "application/pdf")})
    assert response.status_code == 200
    assert len(response.json()["document"]["filename"]) <= 154


def test_invalid_upload_date_is_rejected(api, contract_pdf):
    response = _upload(api, contract_pdf, date="March 2024")
    assert response.status_code == 422
    assert "YYYY-MM-DD" in response.json()["detail"]
    assert api.get("/documents").json() == []
