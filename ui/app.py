import streamlit as st

st.set_page_config(page_title="Document Auditor", page_icon=":material/fact_check:", layout="wide")

pages = [
    st.Page("screens/documents.py", title="Documents", icon=":material/description:", default=True),
    st.Page("screens/search.py", title="Search", icon=":material/search:"),
    st.Page("screens/ask.py", title="Ask", icon=":material/chat:"),
    st.Page("screens/audit.py", title="Audit", icon=":material/fact_check:"),
    st.Page("screens/trace.py", title="Agent trace", icon=":material/timeline:"),
    st.Page("screens/benchmarks.py", title="Benchmarks", icon=":material/leaderboard:"),
]
st.navigation(pages).run()
