import streamlit as st

import shared
from apiclient import ApiError
from viewmodels import SEARCH_COLOR, bbox_annotations, document_label, md_escape

client = shared.get_client()
st.title("Ask the documents")
docs = shared.load_documents(client)
by_id = {doc["document_id"]: doc for doc in docs}

with st.form("ask"):
    question = st.text_input("Question", placeholder="What is the liability cap?")
    selected = st.multiselect("Only these documents (optional)", list(by_id),
                              format_func=lambda i: document_label(by_id[i]))
    asked = st.form_submit_button("Ask", type="primary")

if asked:
    if not question.strip():
        st.warning("Type a question first.")
    else:
        st.session_state.pop("ask_result", None)
        with st.spinner("Searching and answering…"):
            try:
                filters = {"document_ids": selected} if selected else None
                st.session_state["ask_result"] = client.ask(question.strip(), filters)
            except ApiError as exc:
                st.error(exc.detail)

result = st.session_state.get("ask_result")
if result is None:
    st.stop()
if not result["found"]:
    st.info(result["message"])
    for passage in result["passages"]:
        with st.expander(f"Nearest passage · section {md_escape(passage['section_path'] or '-')}"):
            st.markdown(md_escape(passage["text"]))
    st.stop()

st.markdown(f"**{md_escape(result['answer'])}**")
usage = result["usage"]
st.caption(f"{result['model']} · {usage['input_tokens']}/{usage['output_tokens']} tokens · "
           f"${usage['cost_usd']:.4f}")
for number, citation in enumerate(result["citations"], start=1):
    st.markdown(f"> {md_escape(citation['quote'])}")
    source = by_id.get(citation["document_id"])
    name = document_label(source) if source else citation["document_id"][:12]
    st.caption(f"[{number}] {name} · page {citation['page'] or '-'} · "
               f"section {md_escape(citation['section_path'] or '-')}")

first = result["citations"][0]["document_id"]
boxes = [box for c in result["citations"] if c["document_id"] == first for box in c["bboxes"]]
shared.show_source(client, by_id.get(first), bbox_annotations(boxes, SEARCH_COLOR), key="ask_pdf")
