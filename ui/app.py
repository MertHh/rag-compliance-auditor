import streamlit as st

st.set_page_config(page_title="Compliance Auditor", page_icon=":material/gavel:", layout="wide")

pages = [
    st.Page("screens/documents.py", title="Documents", icon=":material/description:", default=True),
    st.Page("screens/search.py", title="Search", icon=":material/search:"),
    st.Page("screens/ask.py", title="Ask", icon=":material/chat:"),
]
st.navigation(pages).run()
