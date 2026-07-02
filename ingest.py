import os
import hashlib
import logging
from document_parser import parse_document, get_supported_files, SUPPORTED_EXTENSIONS
from extractor import extract_knowledge
from knowledge_graph import (
    init_db, document_exists, store_document,
    store_entities, store_relations, clear_domain, clear_all,
    link_domain_entities, store_content_links, get_connection,
)
from config import DOCUMENTS_DIR, llm_describe_image

logger = logging.getLogger("talktodata.ingest")

IGNORE_DIRS = {"venv", "__pycache__", ".git", "node_modules"}


def file_hash(file_path):
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_domain_folders():
    if not os.path.isdir(DOCUMENTS_DIR):
        logger.warning(f"DOCUMENTS_DIR does not exist: {DOCUMENTS_DIR}")
        return []

    folders = []
    for item in os.listdir(DOCUMENTS_DIR):
        item_path = os.path.join(DOCUMENTS_DIR, item)
        if os.path.isdir(item_path) and item not in IGNORE_DIRS and not item.startswith("."):
            has_docs = domain_has_supported_files(item_path)
            if has_docs:
                folders.append((item, item_path))
    return folders


def domain_has_supported_files(domain_path):
    for root, dirs, files in os.walk(domain_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
        for fname in files:
            if os.path.splitext(fname)[1].lower() in SUPPORTED_EXTENSIONS:
                return True
    return False


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
            parsed = parse_document(file_path)
            if isinstance(parsed, tuple):
                text, images = parsed
            else:
                text, images = parsed, []

            if not text.strip() and not images:
                logger.info(f"  Skipping (empty content): {fname}")
                results["skipped"] += 1
                continue

            image_text = ""
            if images:
                logger.info(f"  Describing {len(images)} image(s) via vision LLM")
                for img in images:
                    try:
                        desc = llm_describe_image(img["data"], img.get("mime", "image/png"), text[:200])
                        page_label = f"[Image Page {img['page']}] " if img.get("page") else "[Image] "
                        image_text += f"\n{page_label}{desc}\n"
                    except Exception as img_err:
                        logger.warning(f"  Image description failed: {img_err}")

            full_text = text + image_text if image_text else text
            logger.info(f"  Extracting knowledge graph from: {fname} ({len(full_text)} chars)")
            entities, relations, language = extract_knowledge(full_text)
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

    try:
        content_linked = build_content_links(domain)
        results["content_links"] = content_linked
        logger.info(f"Domain '{domain}': created {content_linked} content link(s)")
    except Exception as e:
        logger.error(f"Domain '{domain}': content linking failed: {str(e)}")
        results["errors"].append(f"content_linking: {str(e)}")

    return results


def build_content_links(domain):
    conn = get_connection()
    rows = conn.execute(
        "SELECT name, entity_type, source_file, source_chunk FROM entities WHERE domain = ?",
        (domain,),
    ).fetchall()
    conn.close()

    entity_locations = {}
    for row in rows:
        key = (row["name"].lower().strip(), row["entity_type"].lower().strip())
        loc = {"file": row["source_file"], "chunk": row["source_chunk"]}
        entity_locations.setdefault(key, []).append(loc)

    links = []
    seen = set()
    for key, locations in entity_locations.items():
        if len(locations) < 2:
            continue
        for i in range(len(locations)):
            for j in range(i + 1, len(locations)):
                a, b = locations[i], locations[j]
                if a["file"] == b["file"] and a["chunk"] == b["chunk"]:
                    continue
                link_key = (a["file"], a["chunk"], b["file"], b["chunk"])
                if link_key in seen:
                    continue
                seen.add(link_key)
                link_type = "cross_document" if a["file"] != b["file"] else "intra_document"
                links.append({
                    "file_a": a["file"], "chunk_a": a["chunk"],
                    "file_b": b["file"], "chunk_b": b["chunk"],
                    "link_type": link_type,
                    "description": f"Shared entity: {key[0]} ({key[1]})",
                    "confidence": 1.0,
                })

    store_content_links(links, domain)
    return len(links)


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
    import argparse

    parser = argparse.ArgumentParser(description="Ingest documents into the knowledge graph")
    parser.add_argument(
        "domains", nargs="*",
        help="Domain folder name(s) to ingest. If omitted, ingests all domains.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Clear existing data and re-ingest from scratch.",
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_domains",
        help="List available domain folders and exit.",
    )
    args = parser.parse_args()

    def print_progress(msg):
        print(f"  {msg}")

    if args.list_domains:
        folders = get_domain_folders()
        if not folders:
            print("No domain folders found.")
        else:
            print("Available domains:")
            for name, path in folders:
                print(f"  {name} ({path})")
        raise SystemExit(0)

    if args.domains:
        available = {name: path for name, path in get_domain_folders()}
        unknown = [d for d in args.domains if d not in available]
        if unknown:
            raise SystemExit(f"Unknown domain(s): {', '.join(unknown)}. Use --list to see available domains.")

        mode = "Re-ingesting" if args.force else "Ingesting"
        print(f"{mode} domain(s): {', '.join(args.domains)}")
        results = {}
        for domain in args.domains:
            results[domain] = ingest_domain(
                domain, available[domain], progress_callback=print_progress, force=args.force,
            )
    else:
        mode = "Re-ingesting all" if args.force else "Ingesting all"
        print(f"{mode} documents...")
        results = ingest_all(progress_callback=print_progress, force=args.force)

    print("\nResults:")
    for domain, r in results.items():
        print(
            f"  {domain}: {r['processed']} processed, {r['skipped']} skipped, "
            f"{r.get('linked_entities', 0)} linked, {len(r['errors'])} errors"
        )
        for err in r["errors"]:
            print(f"    ERROR: {err}")
