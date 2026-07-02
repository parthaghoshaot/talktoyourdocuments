# Chunking, Extraction, and Knowledge Graph Persistence

This document explains how text is chunked, how entities/relations are extracted, and how results are saved and linked in the SQLite knowledge graph.

## End-to-End Pipeline

The ingestion path is orchestrated by [ingest.py](../ingest.py):

1. Parse each supported document into plain text with [document_parser.py](../document_parser.py).
2. Chunk and extract entities/relations with [extractor.py](../extractor.py).
3. Save documents, entities, and relations in [knowledge_graph.py](../knowledge_graph.py).
4. Build canonical cross-document links per domain with `link_domain_entities(domain)`.

## Chunking Logic

Chunking is implemented in `split_into_chunks(text, chunk_size)` in [extractor.py](../extractor.py).

### 1. Text normalization

`normalize_text()` standardizes line breaks and collapses noisy whitespace to reduce parser artifacts.

### 2. Section-aware segmentation

`split_into_sections()` creates higher-quality segment boundaries by using structural markers:

- `[Page N]`
- `[Slide N]`
- `[Sheet: ...]`

These markers are treated as section boundaries so chunks do not blend unrelated document regions.

### 3. Sentence-based chunk building

`build_chunks_from_section()` builds chunks from sentence units:

- Sentences are produced with `split_into_sentences()`.
- A soft semantic break is applied using `should_start_new_chunk()` when lexical overlap with the next sentence drops below a threshold after a minimum chunk size is reached.
- Oversized sentences/paragraphs are split with `split_long_paragraph()` as a fail-safe.
- Chunk overlap is sentence-level (`overlap_sentences=2`) instead of raw character tails.

### 4. Semantic unit chunk building

`build_semantic_chunks_from_section()` adds a second chunk stream at a coarser semantic level:

- `split_into_semantic_units()` groups text into paragraph-like units (split on blank lines and structural markers).
- Chunks are built from these units with light overlap (`overlap_units=1`).
- `should_start_new_semantic_chunk()` introduces boundaries when topic overlap drops after a minimum chunk size.
- Very long units are still split with `split_long_paragraph()`.

This complements sentence chunking by preserving larger topical blocks that may span many sentences.

### 5. Hybrid merge and de-duplication

`merge_chunk_variants()` combines sentence chunks and semantic chunks into one final list:

- sentence chunks are kept as the base,
- semantic chunks are appended only when `is_redundant_chunk()` says they are meaningfully distinct,
- near-duplicates are filtered using normalized text match, containment ratio, and token-overlap checks.

### 6. Relevance filtering before extraction

`score_chunk_relevance(chunk_text)` computes a low-cost quality score using:

- lexical diversity,
- alphabetic token ratio,
- structural-marker penalty.

Very low-score chunks are skipped to avoid extracting noise and boilerplate.

## Extraction Logic

Extraction runs in `extract_knowledge(text, chunk_size=3000)` in [extractor.py](../extractor.py).

1. Iterate over generated chunks.
2. Skip tiny or low-relevance chunks.
3. Call `extract_from_chunk(chunk_text)` which sends the chunk to `llm_chat()` with a strict JSON prompt.
4. Validate minimal shape:
   - entities require `name` and `type`
   - relations require `subject`, `predicate`, `object`
5. Attach provenance to each extracted object:
   - `source_chunk`
   - `source_excerpt` (from model evidence when available, otherwise chunk prefix)
   - `source_page` (when `[Page N]` marker is present)
   - `source_marker` (for `[Page N]`, `[Slide N]`, or `[Sheet: ...]`)
6. Post-process:
   - `deduplicate_entities()` (name-normalized dedup)
   - `normalize_and_deduplicate_relations()` (canonical subject/object mapping + tuple dedup)
7. Add translated fields with `add_translations()`.

## Knowledge Graph Persistence

Storage and schema are managed in [knowledge_graph.py](../knowledge_graph.py).

### Core tables

- `documents`: file-level ingestion metadata (`path`, `domain`, `file_hash`)
- `entities`: extracted entities with provenance fields
- `relations`: extracted triples with provenance fields

Provenance columns used for evidence traceability:

- `source_chunk`
- `source_excerpt`
- `source_page`
- `source_marker`

These fields are used by proof-mode responses to generate clearer citations, including direct file links and PDF page-aware links when available.

### Canonical linking tables

To connect related entities across files in the same domain:

- `canonical_entities`
- `entity_aliases`

`link_domain_entities(domain)` does deterministic clustering:

1. Load all entities in the domain.
2. Normalize names (remove punctuation and organization suffix noise such as `inc`, `ltd`, `gmbh`, etc.).
3. Match against existing canonical candidates by combined token overlap and sequence similarity.
4. Insert alias-to-canonical mapping with confidence.

This creates a cross-document bridge layer without changing raw extracted rows.

## Ingestion Orchestration and Linking

In [ingest.py](../ingest.py), `ingest_domain()` now:

1. Parses and extracts each file.
2. Stores documents/entities/relations.
3. Runs `link_domain_entities(domain)` after all files in the domain are processed.

Result payload includes `linked_entities` so ingestion output reflects cross-document linking activity.

Domain discovery behavior in [ingest.py](../ingest.py):

- domain = first-level folder under `DOCUMENTS_DIR`,
- discovery is recursive inside each domain,
- domains with supported files only in nested subfolders are still discovered and ingested.

## Why This Improves Answer Quality

- Better chunk boundaries reduce concept fragmentation.
- Relevance scoring suppresses low-signal chunks.
- Provenance fields preserve evidence from original text.
- Canonical linking connects related mentions across documents in the same domain.
- Query context can surface stronger, multi-source support for answers.

## Tuning Points

If you want to tune behavior, start with these values in [extractor.py](../extractor.py):

- `chunk_size` in `extract_knowledge()`
- sentence overlap count (`overlap_sentences`)
- lexical-overlap threshold in `should_start_new_chunk()`
- semantic overlap count (`overlap_units`)
- lexical-overlap threshold in `should_start_new_semantic_chunk()`
- relevance cutoff in `extract_knowledge()` for `score_chunk_relevance()`

For cross-document linking in [knowledge_graph.py](../knowledge_graph.py), tune:

- `min_similarity` in `link_domain_entities()`
- normalization rules in `normalize_name_for_match()`
