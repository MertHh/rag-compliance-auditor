import altair as alt
import pandas as pd
import streamlit as st

import shared
from apiclient import ApiError
from viewmodels import label_column, numeric_columns

client = shared.get_client()
st.title("Benchmarks")
try:
    results = client.benchmarks()
except ApiError as exc:
    st.error(exc.detail)
    st.stop()
if not results:
    st.info("No benchmark results yet. The benchmark scripts write them to benchmarks/results/.")
    st.stop()

for result in results:
    st.subheader(result["title"])
    if result["error"]:
        st.warning(result["error"])
        continue
    rows = result["rows"]
    st.dataframe(rows, hide_index=True)
    if result["notes"]:
        st.caption(result["notes"])
    metrics, label = numeric_columns(rows), label_column(rows)
    if not metrics or label is None:
        continue
    metric = st.selectbox("Metric", metrics, key=f"metric_{result['file']}")
    chart = (
        alt.Chart(pd.DataFrame(rows))
        .mark_bar(cornerRadiusEnd=4, color="#2a78d6")
        .encode(
            x=alt.X(f"{metric}:Q", title=metric),
            y=alt.Y(f"{label}:N", title=None, sort="-x"),
            tooltip=[alt.Tooltip(f"{label}:N"), alt.Tooltip(f"{metric}:Q", format=".3f")],
        )
        .properties(height=max(80, 32 * len(rows)))
    )
    st.altair_chart(chart, width="stretch")
