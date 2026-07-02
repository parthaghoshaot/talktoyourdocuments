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

    if folders:
        domain_names = [f[0] for f in folders]
        selected_domain = st.selectbox("Select Domain", ["All"] + domain_names, key="ingest_domain_select")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Ingest", type="primary"):
            target = None if (not folders or selected_domain == "All") else selected_domain
            label = f"domain '{target}'" if target else "all domains"
            with st.spinner(f"Ingesting {label}..."):
                status_placeholder = st.empty()
                cb = lambda msg: status_placeholder.text(msg)
                if target:
                    folder_path = next(p for n, p in folders if n == target)
                    results = {target: ingest_domain(target, folder_path, progress_callback=cb)}
                else:
                    results = ingest_all(progress_callback=cb)
                status_placeholder.empty()
                for d, r in results.items():
                    if r["processed"] > 0:
                        st.success(f"{d}: {r['processed']} new docs processed")
                    if r["skipped"] > 0:
                        st.info(f"{d}: {r['skipped']} docs skipped (already ingested)")
                    for err in r["errors"]:
                        st.error(f"{d}: {err}")

    with col2:
        if st.button("Re-ingest", key="reingest_btn"):
            target = None if (not folders or selected_domain == "All") else selected_domain
            label = f"domain '{target}'" if target else "all domains"
            with st.spinner(f"Re-ingesting {label} (clearing existing data)..."):
                status_placeholder = st.empty()
                cb = lambda msg: status_placeholder.text(msg)
                if target:
                    folder_path = next(p for n, p in folders if n == target)
                    results = {target: ingest_domain(target, folder_path, progress_callback=cb, force=True)}
                else:
                    results = ingest_all(progress_callback=cb, force=True)
                status_placeholder.empty()
                for d, r in results.items():
                    if r["processed"] > 0:
                        st.success(f"{d}: {r['processed']} docs re-ingested")
                    for err in r["errors"]:
                        st.error(f"{d}: {err}")

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
