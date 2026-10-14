import json

import streamlit as st

import shared
from apiclient import ApiError
from viewmodels import citation_annotations, finding_rows, md_escape, run_label, status_label

client = shared.get_client()
st.title("Audit")
docs = shared.load_documents(client)
doc = shared.document_picker(docs)
if doc is None:
    st.stop()

try:
    playbooks = client.playbooks()
    providers = client.providers()
except ApiError as exc:
    st.error(exc.detail)
    st.stop()

for playbook in playbooks:
    if playbook["error"]:
        st.warning(f"Playbook {playbook['key']} cannot be used: {playbook['error']}")
usable = {p["key"]: p for p in playbooks if not p["error"]}
if not usable:
    st.error("No usable playbook. Add a YAML file to the playbooks folder.")
    st.stop()

by_name = {p["name"]: p for p in providers["providers"]}
names = list(by_name)
pick_playbook, pick_provider = st.columns(2)
playbook_key = pick_playbook.selectbox(
    "Playbook", list(usable),
    format_func=lambda k: f"{usable[k]['name']} ({usable[k]['rule_count']} rules)")
provider = pick_provider.selectbox(
    "Model provider", names,
    index=names.index(providers["default"]) if providers["default"] in names else 0,
    format_func=lambda n: f"{n} · {by_name[n]['models']}" if by_name[n]["available"] else f"{n} · unavailable")
if not by_name[provider]["available"]:
    st.warning(by_name[provider]["error"])
force = st.checkbox("Run again even if a saved run exists")

if st.button("Run audit", type="primary", key="run_audit", disabled=not by_name[provider]["available"]):
    try:
        state, payload = client.start_audit(doc["document_id"], playbook_key, provider, force)
    except ApiError as exc:
        st.session_state.pop("audit_id", None)
        st.session_state.pop("audit_saved", None)
        st.error(exc.detail)
    else:
        st.session_state["audit_id"] = payload["audit_id"]
        st.session_state["audit_saved"] = state == "done"


def _pick_history() -> None:
    picked = st.session_state.get("history_pick")
    if picked:
        st.session_state["audit_id"] = picked
        st.session_state["audit_saved"] = True


try:
    history = client.audits(doc["document_id"])
except ApiError:
    history = []
if history:
    runs = {run["audit_id"]: run for run in history}
    st.selectbox(
        "Previous runs", [None, *runs], key="history_pick", on_change=_pick_history,
        format_func=lambda i: "Choose a saved run…" if i is None else
        f"{runs[i]['created_at'][:16].replace('T', ' ')} · {runs[i]['playbook']} · "
        f"{runs[i]['model']} · risk {runs[i]['risk_score']}")

audit_id = st.session_state.get("audit_id")
if not audit_id:
    st.stop()


@st.fragment(run_every=2)
def _wait_for(audit_id: str) -> None:
    try:
        state, _ = client.audit(audit_id)
    except ApiError:
        st.rerun()  # the full run shows the error and stops without polling again
    if state == "done":
        st.rerun()
    st.info("Audit running… findings appear when every rule is done.")


try:
    state, report = client.audit(audit_id)
except ApiError as exc:
    if exc.status == 404:  # the job is gone, e.g. after an API restart
        st.session_state.pop("audit_id", None)
    st.error(exc.detail)
    st.stop()
if report.get("document_id") != doc["document_id"]:
    st.session_state.pop("audit_id", None)
    st.stop()
if state == "running":
    _wait_for(audit_id)
    st.stop()

risk_col, rules_col, time_col, cost_col = st.columns(4)
risk_col.metric("Risk score", "-" if report["risk_score"] is None else f"{report['risk_score']:.1f}")
rules_col.metric("Rules", len(report["findings"]))
time_col.metric("Duration", f"{report['totals']['duration_s']} s")
cost_col.metric("Cost", f"${report['totals']['cost_usd']:.4f}")
saved = st.session_state.get("audit_saved") or report.get("cached")
st.caption(("Saved run · " if saved else "") + run_label(report))
for error in report["errors"]:
    st.error(md_escape(f"{error['rule_id']}: {error['message']}"))
st.dataframe(finding_rows(report), hide_index=True)

findings = {f["rule_id"]: f for f in report["findings"]}
rule_id = st.selectbox("Finding", list(findings),
                       format_func=lambda r: f"{status_label(findings[r]['status'])} · {findings[r]['title']}")
finding = findings[rule_id]
details, source = st.columns([2, 3])
with details:
    st.markdown(f"**{status_label(finding['status'])}** · severity {finding['severity']} · "
                f"risk {finding['risk']}")
    if finding["reasoning"]:
        st.markdown(md_escape(finding["reasoning"]))
    evidence = finding["evidence"]
    st.caption(f"Evidence: {evidence['queries_tried']} queries tried, "
               f"{evidence['sections_examined']} sections examined")
    for citation in finding["citations"]:
        st.markdown(f"> {md_escape(citation['quote'])}")
        st.caption(f"page {citation['page'] or '-'} · "
                   f"section {md_escape(citation['section_path'] or '-')}")
    current = finding["review"]
    with st.form(f"review_{audit_id}_{rule_id}"):
        decision = st.radio("Review", ["accepted", "rejected"], horizontal=True,
                            index=1 if current and current["decision"] == "rejected" else 0,
                            format_func=str.capitalize)
        note = st.text_area("Note", value=current["note"] if current else "")
        if st.form_submit_button("Save review"):
            try:
                client.review(audit_id, rule_id, decision, note)
            except ApiError as exc:
                st.error(exc.detail)
            else:
                st.success("Review saved.")
with source:
    shared.show_source(client, doc, citation_annotations([finding]), key="audit_pdf")

st.subheader("Export")
json_col, pdf_col = st.columns(2)
json_col.download_button("Download JSON", json.dumps(report, ensure_ascii=False, indent=2),
                         file_name=f"audit-{audit_id}.json", mime="application/json")
if pdf_col.button("Prepare PDF report"):
    try:
        st.session_state["audit_pdf"] = (audit_id, client.export(audit_id, "pdf"))
    except ApiError as exc:
        st.error(exc.detail)
prepared = st.session_state.get("audit_pdf")
if prepared and prepared[0] == audit_id:
    pdf_col.download_button("Download PDF", prepared[1], file_name=f"audit-{audit_id}.pdf",
                            mime="application/pdf")
