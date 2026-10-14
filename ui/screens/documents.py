import streamlit as st

import shared
from apiclient import ApiError
from viewmodels import document_rows

client = shared.get_client()
st.title("Documents")

with st.form("upload", clear_on_submit=True):
    file = st.file_uploader("Contract PDF", type=["pdf"])
    left, middle, right = st.columns(3)
    doc_type = left.text_input("Document type (optional)")
    signed = middle.text_input("Date, YYYY-MM-DD (optional)")
    jurisdiction = right.text_input("Jurisdiction (optional)")
    parties = st.text_input("Parties, comma separated (optional)")
    extract = st.checkbox("Fill empty fields with the LLM", value=True)
    submitted = st.form_submit_button("Upload and index", type="primary")

if submitted:
    if file is None:
        st.warning("Choose a PDF first.")
    else:
        metadata = {
            "doc_type": doc_type.strip() or None,
            "date": signed.strip() or None,
            "jurisdiction": jurisdiction.strip() or None,
            "parties": [p.strip() for p in parties.split(",") if p.strip()] or None,
        }
        with st.spinner("Parsing, embedding and indexing…"):
            try:
                result = client.upload(file.name, file.getvalue(), metadata, extract)
            except ApiError as exc:
                st.error(exc.detail)
            else:
                for warning in result["warnings"]:
                    st.warning(warning)
                name = result["document"]["filename"]
                if result["already_indexed"]:
                    st.info(f"{name} is already indexed.")
                else:
                    st.success(f"Indexed {result['chunk_count']} chunks from {name}.")

docs = shared.load_documents(client)
if not docs:
    st.info("No documents yet. Upload a contract PDF above.")
    st.stop()
st.dataframe(document_rows(docs), hide_index=True)
