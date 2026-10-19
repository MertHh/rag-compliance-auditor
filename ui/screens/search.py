import streamlit as st

import shared
from apiclient import ApiError
from viewmodels import SEARCH_COLOR, bbox_annotations, build_filters, document_label, search_rows

client = shared.get_client()
st.title("Search")
docs = shared.load_documents(client)
by_id = {doc["document_id"]: doc for doc in docs}

linked = shared.from_link("q")
if linked:
    st.session_state["search_query"] = linked
query = st.text_input("Query", key="search_query", placeholder="limitation of liability")
mode_col, rerank_col, k_col = st.columns(3)
mode = mode_col.selectbox("Mode", ["hybrid", "bm25", "dense"])
rerank = rerank_col.toggle("Rerank", value=True)
final_k = k_col.number_input("Results", min_value=1, max_value=30, value=5)
with st.expander("Filters"):
    document_ids = st.multiselect("Documents", list(by_id),
                                  format_func=lambda i: document_label(by_id[i]))
    doc_types = st.multiselect("Document type", sorted({d["doc_type"] for d in docs if d["doc_type"]}))
    jurisdictions = st.multiselect("Jurisdiction",
                                   sorted({d["jurisdiction"] for d in docs if d["jurisdiction"]}))
    from_col, to_col = st.columns(2)
    date_from = from_col.date_input("Signed from", value=None)
    date_to = to_col.date_input("Signed to", value=None)

if not query.strip():
    st.info("Type a query to see how each stage ranks the clauses.")
    st.stop()

filters = build_filters(document_ids, doc_types, jurisdictions, date_from, date_to)
try:
    result = client.search(query.strip(), mode, rerank, int(final_k), filters)
except ApiError as exc:
    st.error(exc.detail)
    st.stop()

if result["insufficient_evidence"]:
    st.warning("Weak evidence: the best match scores below the rerank threshold.")
if not result["chunks"]:
    st.stop()
st.dataframe(search_rows(result), hide_index=True)
st.caption("Change = rank after fusion minus final rank; positive means the reranker moved it up.")

chunks = {chunk["chunk_id"]: chunk for chunk in result["chunks"]}
chosen = st.selectbox(
    "Show in the PDF", list(chunks),
    format_func=lambda c: f"#{chunks[c]['scores']['final_rank']} · {chunks[c]['section_path'] or '-'}",
)
chunk = chunks[chosen]
shared.show_source(client, by_id.get(chunk["document_id"]),
                   bbox_annotations(chunk["bboxes"], SEARCH_COLOR), key="search_pdf")
