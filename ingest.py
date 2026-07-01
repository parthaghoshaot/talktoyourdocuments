import os
import hashlib
import logging
from document_parser import parse_document, get_supported_files, SUPPORTED_EXTENSIONS
from extractor import extract_knowledge
from knowledge_graph import (
    init_db, document_exists, store_document,
    store_entities, store_relations, clear_domain, clear_all,
    link_domain_entities,
)
from config import DOCUMENTS_DIR

logger = logging.getLogger("talktodata.ingest")

IGNORE_DIRS = {"venv", "__pycache__", ".git", "node_modules"}


def file_hash(file_path):
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_domain_folders():
    folders = []
    for item in os.listdir(DOCUMENTS_DIR):
        item_path = os.path.join(DOCUMENTS_DIR, item)
        if os.path.isdir(item_path) and item not in IGNORE_DIRS and not item.startswith("."):
            has_docs = any(
                os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
                for f in os.listdir(item_path) if os.path.isfile(os.path.join(item_path, f))
            )
            if has_docs:
                folders.append((item, item_path))
    return folders


def ingest_domain(domain, folder_path, progress_callback=None, force=False):
    init_db()
    if force:
        logger.info(f"Force re-ingest: clearing domain '{domain}'")
        clear_domain(domain)
    files = get_supported_files(folder_path)
    logger.info(f"Domain '{domain}': found {len(files)} file(s) to process")
    results = {"processed": 0, "skipped": 0, "errors": [], "linked_entities": 0}

    for i, file_path in enumerate(files):
        fname = os.path.basename(file_path)
        if progress_callback:
            progress_callback(f"Processing ({i+1}/{len(files)}): {fname}")

        fhash = file_hash(file_path)
        if not force and document_exists(fhash):
            logger.info(f"  Skipping (already ingested): {fname}")
            results["skipped"] += 1
            continue

        try:
            logger.info(f"  Parsing document: {fname}")
            text = parse_document(file_path)
            if not text.strip():
                logger.info(f"  Skipping (empty content): {fname}")
                results["skipped"] += 1
                continue

            logger.info(f"  Extracting knowledge graph from: {fname} ({len(text)} chars)")
            entities, relations, language = extract_knowledge(text)
            logger.info(f"  Extracted: {len(entities)} entities, {len(relations)} relations, language={language}")
            store_document(file_path, domain, fhash)
            if entities:
                store_entities(entities, domain, file_path, language)
            if relations:
                store_relations(relations, domain, file_path, language)
            logger.info(f"  Stored in KG: {fname}")
            results["processed"] += 1
        except Exception as e:
            logger.error(f"  Error processing {fname}: {str(e)}")
            results["errors"].append(f"{fname}: {str(e)}")

    try:
        linked = link_domain_entities(domain)
        results["linked_entities"] = linked
        logger.info(f"Domain '{domain}': linked {linked} entities across documents")
    except Exception as e:
        logger.error(f"Domain '{domain}': entity linking failed: {str(e)}")
        results["errors"].append(f"entity_linking: {str(e)}")

    return results


def ingest_all(progress_callback=None, force=False):
    init_db()
    if force:
        logger.info("Force re-ingest: clearing ALL data")
        clear_all()
    all_results = {}
    folders = get_domain_folders()
    logger.info(f"Starting ingestion: {len(folders)} domain(s) found")

    for domain, folder_path in folders:
        if progress_callback:
            progress_callback(f"Ingesting domain: {domain}")
        results = ingest_domain(domain, folder_path, progress_callback, force=force)
        all_results[domain] = results

    return all_results


if __name__ == "__main__":
    def print_progress(msg):
        print(f"  {msg}")

    print("Starting document ingestion...")
    results = ingest_all(progress_callback=print_progress)
    print("\nResults:")
    for domain, r in results.items():
        print(
            f"  {domain}: {r['processed']} processed, {r['skipped']} skipped, "
            f"{r.get('linked_entities', 0)} linked, {len(r['errors'])} errors"
        )
        for err in r["errors"]:
            print(f"    ERROR: {err}")
