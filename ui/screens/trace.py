import altair as alt
import pandas as pd
import streamlit as st

import shared
from apiclient import ApiError
from viewmodels import NODE_COLORS, NODE_ORDER, rule_totals, trace_rows

client = shared.get_client()
st.title("Agent trace")
try:
    audits = client.audits()
except ApiError as exc:
    st.error(exc.detail)
    st.stop()
if not audits:
    st.info("No audits yet. Run one on the Audit page.")
    st.stop()

runs = {run["audit_id"]: run for run in audits}
ids = list(runs)
current = st.session_state.get("audit_id")
audit_id = st.selectbox(
    "Audit", ids, index=ids.index(current) if current in ids else 0,
    format_func=lambda i: f"{runs[i]['created_at'][:16].replace('T', ' ')} · {runs[i]['playbook']} · "
                          f"{runs[i]['model']}")
try:
    rows = trace_rows(client.trace(audit_id))
except ApiError as exc:
    st.error(exc.detail)
    st.stop()
if not rows:
    st.info("This audit recorded no steps.")
    st.stop()

rules = sorted({row["rule_id"] for row in rows})
picked = st.multiselect("Rules", rules, default=rules)
shown = [row for row in rows if row["rule_id"] in picked]
if not shown:
    st.stop()

chart = (
    alt.Chart(pd.DataFrame(shown))
    .mark_bar(cornerRadius=3, height=14)
    .encode(
        x=alt.X("start_s:Q", title="Seconds since the audit started"),
        x2="end_s:Q",
        y=alt.Y("rule_id:N", title=None, sort=picked),
        color=alt.Color("node:N", title="Step",
                        scale=alt.Scale(domain=NODE_ORDER, range=NODE_COLORS),
                        legend=alt.Legend(orient="top")),
        tooltip=[
            alt.Tooltip("rule_id:N", title="Rule"),
            alt.Tooltip("node:N", title="Step"),
            alt.Tooltip("duration_s:Q", title="Seconds", format=".2f"),
            alt.Tooltip("tokens:Q", title="Tokens"),
            alt.Tooltip("cost_usd:Q", title="Cost ($)", format=".4f"),
            alt.Tooltip("output:N", title="Output"),
        ],
    )
    .properties(height=max(120, 30 * len(picked)))
)
st.altair_chart(chart, width="stretch")
st.dataframe(rule_totals(shown), hide_index=True)
with st.expander("Every step"):
    st.dataframe(pd.DataFrame(shown)[["rule_id", "node", "start_s", "duration_s", "tokens",
                                      "cost_usd", "models", "input", "output"]], hide_index=True)
