# Talk to Your Documents

A Python application that uses **Knowledge Graph extraction** (Google Open Knowledge Graph format) instead of traditional RAG to understand and answer questions about your documents.

## How It Works

```
Documents (PDF/Word/Excel/PPT)
        │
        ▼
   Parse Text ──► Translate (German→English) ──► LLM Extraction
        │                                              │
        │                                              ▼
        │                                   Entities + Relations
        │                                              │
        ▼                                              ▼
   SQLite Knowledge Graph ◄────────────────── Store Triples
        │
        ▼
   User Question ──► Search KG ──► Build Context ──► LLM Answer
```

**Instead of vector embeddings (RAG)**, this app:
1. Extracts **entities** (people, organizations, concepts, processes) from your documents
2. Extracts **relationships** between those entities (subject → predicate → object triples)
3. Stores everything in a persistent SQLite knowledge graph
4. When you ask a question, it searches the graph for relevant entities/relations and uses them as context for the LLM to generate an answer

## Technical Documentation

- Chunking, extraction, and KG persistence details: [docs/chunking-extraction-kg.md](docs/chunking-extraction-kg.md)

## Setup

### 1. Create Virtual Environment

```bash
cd talktodata
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure API Keys

```bash
cp .env.example .env
```

Edit `.env` and add your API key for the provider you want to use. Default is OpenAI:

```
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-actual-key-here
LLM_BASE_URL
```

### 4. Add Documents

Place your documents in domain-specific folders at the project root:

```
talktodata/
├── ubuy/                    ← domain folder
│   ├── instructions.pdf
│   └── guide.docx
├── sometopic/               ← another domain folder
│   ├── report.xlsx
│   └── presentation.pptx
```

Each folder = one domain. The app automatically discovers folders that contain supported documents.

**Supported formats:** PDF, DOCX, PPTX, XLSX

### 5. Run the App

```bash
streamlit run app.py
```

Opens in your browser at `http://localhost:8501`

## Usage

1. **Ingest Documents**: Click "Ingest All Documents" in the sidebar. This parses, chunks text using sentence + semantic segmentation, translates (if German), extracts knowledge, and stores it.
2. **Ask Questions**: Type your question in the chat input. The app searches the knowledge graph and generates an answer.
     - For document proof, include terms like "proof", "evidence", "citation", or "source" in your question.
     - The response appends a **PROOF FROM ORIGINAL DOCUMENTS** section with clickable file links.
     - For PDFs, citations include page-aware links (for example, `file.pdf p.12`).
3. **Filter by Domain**: Use the sidebar dropdown to limit answers to a specific domain folder.
4. **Check Stats**: The sidebar shows how many entities and relations were extracted per domain.

If your data was ingested before this citation update, run **Re-ingest All Documents** once to populate precise source markers/page metadata.

## Switching LLM Providers

Edit `LLM_PROVIDER` in your `.env` file:

| Provider | Value | Requires |
|----------|-------|----------|
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Google Gemini | `gemini` | `GEMINI_API_KEY` |
| Anthropic Claude | `anthropic` | `ANTHROPIC_API_KEY` |
| Ollama (local) | `ollama` | Ollama running locally |

Restart the app after changing the provider.

## Command-Line Ingestion

You can also ingest documents without the UI:

```bash
python ingest.py
```

## Project Structure

| File | Purpose |
|------|---------|
| `app.py` | Streamlit chat UI |
| `config.py` | LLM provider factory, settings |
| `document_parser.py` | Parse PDF/Word/Excel/PPT to text |
| `translator.py` | Detect language, translate German→English |
| `extractor.py` | LLM-based entity/relation extraction |
| `knowledge_graph.py` | SQLite-backed KG storage and queries |
| `query_engine.py` | Search KG + generate answers |
| `ingest.py` | Orchestrates the full ingestion pipeline |

## Notes

- **German documents** are automatically translated to English during ingestion. The knowledge graph is stored in English. You ask questions in English.
- **Deduplication**: Documents are tracked by file hash. Re-running ingestion skips already-processed files.
- **Session memory**: The chat remembers your conversation for the current session. Refreshing the page starts a new session.
- **Future: persistent history** — code is structured to allow adding session persistence (DB-backed chat history) later.
