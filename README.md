# Talk to Your Documents

A Python application that uses **Knowledge Graph extraction** (Google Open Knowledge Graph format) instead of traditional RAG to understand and answer questions about your documents.

## How It Works

```
Documents (PDF/Word/Excel/PPT)
        │
        ├──► Parse Text + Headings ──► Hierarchical Chunking
        │                                      │
        └──► Extract Images ──► Vision LLM ────┤
                                               ▼
                                    LLM Extraction (with confidence)
                                               │
                                               ▼
                                    Entities + Relations
                                               │
                                    Coreference Resolution
                                               │
                                               ▼
   SQLite Knowledge Graph ◄────────── Store Triples + Links
        │
        ├── Canonical Entity Linking (cross-document)
        └── Content Links (chunk-to-chunk)
        │
        ▼
   User Question ──► Search KG + Cross-refs ──► LLM Answer
```

**Instead of vector embeddings (RAG)**, this app:
1. Extracts **entities** (people, organizations, concepts, processes) from your documents — including images, diagrams, and charts via vision LLM
2. Extracts **relationships** between those entities (subject → predicate → object triples) with confidence scores
3. Resolves coreferences across chunks (e.g., "the company" → "SomeCompany GmbH")
4. Stores everything in a persistent SQLite knowledge graph with cross-document content links
5. When you ask a question, it searches the graph for relevant entities/relations/cross-references and uses them as context for the LLM to generate an answer

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
LLM_BASE_URL=your-llm-end-point
```

### Runtime Root (Optional, Recommended)

Set `TALKTODATA_HOME` to keep `.env`, `knowledge.db`, and `documents/` together in one runtime folder.

When `TALKTODATA_HOME` is set:

- `.env` is loaded from `${TALKTODATA_HOME}/.env`
- DB is stored at `${TALKTODATA_HOME}/knowledge.db`
- Domain documents are read from `${TALKTODATA_HOME}/documents/`

Example (portable Desktop setup):

```bash
export TALKTODATA_HOME="$HOME/Desktop/TalkToData-data"
mkdir -p "$TALKTODATA_HOME/documents"
```

If `TALKTODATA_HOME` is not set, the app keeps the legacy source-mode behavior and uses the project root.

### 4. Add Documents

Place your documents in domain-specific folders at the project root:

```
talktodata/
├── anothertopic/                    ← domain folder
│   ├── instructions.pdf
│   └── guide.docx
├── sometopic/               ← another domain folder
│   ├── report.xlsx
│   └── presentation.pptx
```

Each folder = one domain. The app automatically discovers folders that contain supported documents.

Nested folders are supported inside each domain. For example:

```
documents/
├── anothertopic/
│   ├── onboarding/
│   │   └── instructions.pdf
│   └── policies/
│       └── guide.docx
└── sometopic/
     └── research/
          └── report.xlsx
```

Domain detection is recursive, so a domain is discovered even if files are only in subfolders.

**Supported formats:** PDF, DOCX, PPTX, XLSX

### 5. Run the App

```bash
streamlit run app.py
```

Opens in your browser at `http://localhost:8501`

To match packaged-app behavior during local testing, run with the same `TALKTODATA_HOME` value in VS Code terminals before using `streamlit` or `python ingest.py`.

### Run From VS Code (Launch Profiles)

A ready launch profile is included in [.vscode/launch.json](.vscode/launch.json).

Use it like this:

1. Open **Run and Debug** in VS Code.
2. Select one of:
     - `TalkToData: Streamlit (TALKTODATA_HOME)`
     - `TalkToData: Ingest CLI (TALKTODATA_HOME)`
3. Press **Start Debugging**.

Both launch profiles set:

```bash
TALKTODATA_HOME=$HOME/Desktop/TalkToData-data
```

So Streamlit and CLI ingest use the same `.env`, DB, and documents folder layout.

### Package As macOS App (Copy Anywhere)

For local packaging without opening VS Code each time, use the included [launcher.py](launcher.py) and [setup.py](setup.py):

One-command build:

```bash
chmod +x scripts/build-macos-app.sh
scripts/build-macos-app.sh
```

Optional custom output folder:

```bash
scripts/build-macos-app.sh "$HOME/Desktop/MyTalkToData"
```

Manual equivalent (what the script does):

```bash
cd /Users/GHOSHPA/Github/local/talktodata

python3 -m venv .build-venv
source .build-venv/bin/activate
pip install -r requirements.txt
pip install py2app setuptools

python setup.py py2app

mkdir -p "$HOME/Desktop/TalkToData-Portable"
cp -R "dist/TalkToData.app" "$HOME/Desktop/TalkToData-Portable/"

mkdir -p "$HOME/Desktop/TalkToData-Portable/TalkToData-data/documents"
cp .env.example "$HOME/Desktop/TalkToData-Portable/TalkToData-data/.env"
```

Then:

1. Edit `$HOME/Desktop/TalkToData-Portable/TalkToData-data/.env` with your real keys.
2. Add documents under `$HOME/Desktop/TalkToData-Portable/TalkToData-data/documents/<domain>/...`.
3. Double-click `TalkToData.app`.

By default, the packaged app writes to a companion folder next to the app:

- `TalkToData-data/.env`
- `TalkToData-data/knowledge.db`
- `TalkToData-data/documents/`

You can move the whole `TalkToData-Portable` folder anywhere, and the app keeps using that local companion data folder.

## Usage

1. **Ingest Documents**: Click "Ingest All Documents" in the sidebar. The pipeline:
   - Parses text with heading hierarchy detection
   - Extracts images and describes them via vision LLM
   - Chunks using sentence + semantic segmentation with section breadcrumbs
   - Translates (if German)
   - Extracts entities/relations with confidence scores
   - Resolves coreferences across chunks
   - Builds cross-document and intra-document content links
2. **Ask Questions**: Type your question in the chat input. The app searches the knowledge graph and generates an answer.
     - For document proof, include terms like "proof", "evidence", "citation", or "source" in your question.
     - The response appends a **PROOF FROM ORIGINAL DOCUMENTS** section with clickable file links.
     - For PDFs, citations include page-aware links (for example, `file.pdf p.12`).
     - Cross-references between documents are surfaced when relevant.
3. **Filter by Domain**: Use the sidebar dropdown to limit answers to a specific domain folder.
4. **Check Stats**: The sidebar shows how many entities and relations were extracted per domain.

If your data was ingested before the latest updates, run **Re-ingest All Documents** (or `python ingest.py --force`) to get image extraction, confidence scores, coreference resolution, and content links.

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
# Ingest all domains
python ingest.py

# List available domains
python ingest.py --list

# Ingest specific domain(s)
python ingest.py sometopic
python ingest.py anothertopic sometopic

# Re-ingest all (clear existing data + fresh extraction)
python ingest.py --force

# Re-ingest specific domain(s)
python ingest.py sometopic --force
```

## Project Structure

| File | Purpose |
|------|---------|
| `app.py` | Streamlit chat UI |
| `config.py` | LLM provider factory, settings, vision LLM support |
| `document_parser.py` | Parse PDF/Word/Excel/PPT to text + images with heading detection |
| `translator.py` | Detect language, translate German→English |
| `extractor.py` | Hierarchical chunking, LLM extraction with confidence, coreference resolution |
| `knowledge_graph.py` | SQLite-backed KG storage, cross-document linking, content links |
| `query_engine.py` | Search KG + cross-references + generate answers |
| `ingest.py` | Orchestrates ingestion pipeline with domain-wise/selective ingest |

## Extraction Pipeline Details

### Image Extraction
- **PDF**: Extracts embedded images via PyMuPDF pixmaps (skips icons < 5KB, max 20 per doc)
- **DOCX**: Extracts from document relationship parts
- **PPTX**: Extracts from picture shapes per slide
- Images are described by a vision-capable LLM (GPT-4o, Gemini) and the descriptions are fed into KG extraction

### Hierarchical Chunking
- Detects heading hierarchy from DOCX paragraph styles and PDF font sizes
- Each chunk carries a `[Section: H1 > H2 > H3]` breadcrumb prefix
- Headings act as section boundaries for chunking (prevents blending unrelated content)

### Coreference Resolution
- After initial extraction, all entity names are sent to the LLM in a second pass
- Pronouns, abbreviations, and partial names are resolved to canonical forms
- Both entities and relations are updated with resolved names

### Cross-Document Linking
- Entities appearing in multiple chunks/files create explicit `content_links`
- Links are typed as `intra_document` or `cross_document`
- Surfaced in query context as cross-references

### Confidence Scoring
- LLM rates each extracted entity/relation from 0.0 to 1.0
- Extractions below 0.3 are discarded
- Query ranking boosts high-confidence results

## Notes

- **German documents** are automatically translated to English during ingestion. The knowledge graph is stored in English. You ask questions in English.
- **Deduplication**: Documents are tracked by file hash. Re-running ingestion skips already-processed files.
- **Vision support**: Requires a vision-capable model (GPT-4o, Gemini). Images in documents are automatically processed during ingestion.
- **Session memory**: The chat remembers your conversation for the current session. Refreshing the page starts a new session.
- **Future: persistent history** — code is structured to allow adding session persistence (DB-backed chat history) later.
