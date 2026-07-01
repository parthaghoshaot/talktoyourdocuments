import streamlit as st
from knowledge_graph import init_db, get_domain_stats, get_all_domains, clear_all
from query_engine import answer_question
from ingest import ingest_all, ingest_domain, get_domain_folders

init_db()

st.set_page_config(page_title="Talk to Data", page_icon="📄", layout="wide")
st.title("📄 Talk to Your Documents")

# Session state initialization
if "messages" not in st.session_state:
    st.session_state.messages = []
if "domain_filter" not in st.session_state:
    st.session_state.domain_filter = None

# Sidebar
with st.sidebar:
    st.header("Settings")

    domains = get_all_domains()
    domain_options = ["All Domains"] + domains
    selected = st.selectbox("Filter by Domain", domain_options)
    st.session_state.domain_filter = None if selected == "All Domains" else selected

    st.divider()
    st.header("Document Ingestion")

    folders = get_domain_folders()
    if folders:
        folder_names = [f[0] for f in folders]
        st.write(f"Found {len(folders)} domain folder(s): {', '.join(folder_names)}")
    else:
        st.write("No domain folders with documents found.")

    if st.button("Ingest All Documents", type="primary"):
        with st.spinner("Ingesting documents..."):
            status_placeholder = st.empty()

            def update_status(msg):
                status_placeholder.text(msg)

            results = ingest_all(progress_callback=update_status)
            status_placeholder.empty()

            for domain, r in results.items():
                if r["processed"] > 0:
                    st.success(f"{domain}: {r['processed']} new docs processed")
                if r["skipped"] > 0:
                    st.info(f"{domain}: {r['skipped']} docs skipped (already ingested)")
                for err in r["errors"]:
                    st.error(f"{domain}: {err}")

    if st.button("Re-ingest All Documents", key="reingest_btn"):
        with st.spinner("Re-ingesting all documents (clearing existing data)..."):
            status_placeholder = st.empty()

            def update_reingest_status(msg):
                status_placeholder.text(msg)

            results = ingest_all(progress_callback=update_reingest_status, force=True)
            status_placeholder.empty()

            for domain, r in results.items():
                if r["processed"] > 0:
                    st.success(f"{domain}: {r['processed']} docs re-ingested")
                for err in r["errors"]:
                    st.error(f"{domain}: {err}")

    st.divider()
    st.header("Knowledge Graph Stats")
    stats = get_domain_stats()
    if stats:
        for domain, s in stats.items():
            st.metric(f"📁 {domain}", f"{s['entities']} entities, {s['relations']} relations")
            st.caption(f"{s['documents']} document(s)")
    else:
        st.write("No data ingested yet. Click 'Ingest All Documents' to start.")

    st.divider()
    if st.button("Clear Chat History"):
        st.session_state.messages = []
        st.rerun()

# Chat interface
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask a question about your documents..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            history = st.session_state.messages[:-1]
            domain = st.session_state.domain_filter
            response = answer_question(prompt, history, domain)
        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
