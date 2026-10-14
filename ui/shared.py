import streamlit as st

import pdfview
from apiclient import ApiClient, ApiError
from viewmodels import document_label


@st.cache_resource
def get_client() -> ApiClient:
    return ApiClient.from_env()


def load_documents(client: ApiClient) -> list[dict]:
    try:
        return client.documents()
    except ApiError as exc:
        st.error(exc.detail)
        st.stop()


def document_picker(docs: list[dict], label: str = "Document") -> dict | None:
    """A document selector whose choice carries over between pages."""
    if not docs:
        st.info("No documents yet. Upload a contract on the Documents page.")
        return None
    by_id = {doc["document_id"]: doc for doc in docs}
    ids = list(by_id)
    current = st.session_state.get("document_id")
    chosen = st.selectbox(label, ids, index=ids.index(current) if current in ids else 0,
                          format_func=lambda document_id: document_label(by_id[document_id]))
    st.session_state["document_id"] = chosen
    return by_id[chosen]


@st.cache_data(show_spinner=False, max_entries=8)
def _pdf_bytes(_client: ApiClient, document_id: str) -> bytes:
    return _client.document_file(document_id)


def show_source(client: ApiClient, doc: dict | None, annotations: list[dict], key: str) -> None:
    if doc is None:
        return
    if not doc["has_pdf"]:
        st.caption("This document was indexed from plain text; there is no PDF to highlight.")
        return
    try:
        data = _pdf_bytes(client, doc["document_id"])
    except ApiError as exc:
        st.error(exc.detail)
        return
    pdfview.show_pdf(data, annotations, key=key)
