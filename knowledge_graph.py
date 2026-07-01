import sqlite3
import os
import re
from difflib import SequenceMatcher
from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            domain TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            last_ingested TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_translated TEXT,
            entity_type TEXT NOT NULL,
            description TEXT,
            description_translated TEXT,
            source_chunk INTEGER,
            source_excerpt TEXT,
            source_page INTEGER,
            source_marker TEXT,
            language TEXT NOT NULL DEFAULT 'en',
            domain TEXT NOT NULL,
            source_file TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            subject_translated TEXT,
            predicate TEXT NOT NULL,
            object TEXT NOT NULL,
            object_translated TEXT,
            context TEXT,
            context_translated TEXT,
            source_chunk INTEGER,
            source_excerpt TEXT,
            source_page INTEGER,
            source_marker TEXT,
            language TEXT NOT NULL DEFAULT 'en',
            domain TEXT NOT NULL,
            source_file TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS canonical_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS entity_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL UNIQUE,
            canonical_id INTEGER NOT NULL,
            alias_name TEXT NOT NULL,
            confidence REAL NOT NULL,
            source_file TEXT NOT NULL,
            FOREIGN KEY (entity_id) REFERENCES entities(id),
            FOREIGN KEY (canonical_id) REFERENCES canonical_entities(id)
        );

        CREATE INDEX IF NOT EXISTS idx_entities_domain ON entities(domain);
        CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
        CREATE INDEX IF NOT EXISTS idx_relations_domain ON relations(domain);
        CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject);
        CREATE INDEX IF NOT EXISTS idx_relations_object ON relations(object);
        CREATE INDEX IF NOT EXISTS idx_documents_domain ON documents(domain);
        CREATE INDEX IF NOT EXISTS idx_canonical_entities_domain ON canonical_entities(domain);
        CREATE INDEX IF NOT EXISTS idx_entity_aliases_canonical_id ON entity_aliases(canonical_id);
    """)
    ensure_column(conn, "entities", "source_chunk", "INTEGER")
    ensure_column(conn, "entities", "source_excerpt", "TEXT")
    ensure_column(conn, "entities", "source_page", "INTEGER")
    ensure_column(conn, "entities", "source_marker", "TEXT")
    ensure_column(conn, "relations", "source_chunk", "INTEGER")
    ensure_column(conn, "relations", "source_excerpt", "TEXT")
    ensure_column(conn, "relations", "source_page", "INTEGER")
    ensure_column(conn, "relations", "source_marker", "TEXT")
    conn.commit()
    conn.close()


def ensure_column(conn, table_name, column_name, column_def):
    cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    col_names = {row[1] for row in cols}
    if column_name not in col_names:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def document_exists(file_hash):
    conn = get_connection()
    row = conn.execute("SELECT id FROM documents WHERE file_hash = ?", (file_hash,)).fetchone()
    conn.close()
    return row is not None


def store_document(path, domain, file_hash):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO documents (path, domain, file_hash) VALUES (?, ?, ?)",
        (path, domain, file_hash)
    )
    conn.commit()
    conn.close()


def store_entities(entities, domain, source_file, language="en"):
    conn = get_connection()
    conn.executemany(
        "INSERT INTO entities (name, name_translated, entity_type, description, description_translated, source_chunk, source_excerpt, source_page, source_marker, language, domain, source_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(
            e["name"],
            e.get("name_translated", ""),
            e["type"],
            e.get("description", ""),
            e.get("description_translated", ""),
            e.get("source_chunk"),
            e.get("source_excerpt", ""),
            e.get("source_page"),
            e.get("source_marker", ""),
            language,
            domain,
            source_file,
        ) for e in entities]
    )
    conn.commit()
    conn.close()


def store_relations(relations, domain, source_file, language="en"):
    conn = get_connection()
    conn.executemany(
        "INSERT INTO relations (subject, subject_translated, predicate, object, object_translated, context, context_translated, source_chunk, source_excerpt, source_page, source_marker, language, domain, source_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(
            r["subject"],
            r.get("subject_translated", ""),
            r["predicate"],
            r["object"],
            r.get("object_translated", ""),
            r.get("context", ""),
            r.get("context_translated", ""),
            r.get("source_chunk"),
            r.get("source_excerpt", ""),
            r.get("source_page"),
            r.get("source_marker", ""),
            language,
            domain,
            source_file,
        ) for r in relations]
    )
    conn.commit()
    conn.close()


def search_entities(query, domain=None):
    conn = get_connection()
    q = f"%{query}%"
    if domain:
        rows = conn.execute(
            "SELECT * FROM entities WHERE (name LIKE ? OR name_translated LIKE ? OR description LIKE ? OR description_translated LIKE ? OR source_excerpt LIKE ?) AND domain = ?",
            (q, q, q, q, q, domain)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM entities WHERE name LIKE ? OR name_translated LIKE ? OR description LIKE ? OR description_translated LIKE ? OR source_excerpt LIKE ?",
            (q, q, q, q, q)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_relations(query, domain=None):
    conn = get_connection()
    q = f"%{query}%"
    if domain:
        rows = conn.execute(
            "SELECT * FROM relations WHERE (subject LIKE ? OR subject_translated LIKE ? OR object LIKE ? OR object_translated LIKE ? OR predicate LIKE ? OR context LIKE ? OR context_translated LIKE ? OR source_excerpt LIKE ?) AND domain = ?",
            (q, q, q, q, q, q, q, q, domain)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM relations WHERE subject LIKE ? OR subject_translated LIKE ? OR object LIKE ? OR object_translated LIKE ? OR predicate LIKE ? OR context LIKE ? OR context_translated LIKE ? OR source_excerpt LIKE ?",
            (q, q, q, q, q, q, q, q)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_domains():
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT domain FROM documents ORDER BY domain").fetchall()
    conn.close()
    return [r["domain"] for r in rows]


def get_domain_stats():
    conn = get_connection()
    stats = {}
    domains = conn.execute("SELECT DISTINCT domain FROM documents").fetchall()
    for d in domains:
        domain = d["domain"]
        doc_count = conn.execute("SELECT COUNT(*) as c FROM documents WHERE domain = ?", (domain,)).fetchone()["c"]
        entity_count = conn.execute("SELECT COUNT(*) as c FROM entities WHERE domain = ?", (domain,)).fetchone()["c"]
        relation_count = conn.execute("SELECT COUNT(*) as c FROM relations WHERE domain = ?", (domain,)).fetchone()["c"]
        stats[domain] = {"documents": doc_count, "entities": entity_count, "relations": relation_count}
    conn.close()
    return stats


def clear_domain(domain):
    conn = get_connection()
    conn.execute(
        "DELETE FROM entity_aliases WHERE canonical_id IN (SELECT id FROM canonical_entities WHERE domain = ?)",
        (domain,),
    )
    conn.execute("DELETE FROM canonical_entities WHERE domain = ?", (domain,))
    conn.execute("DELETE FROM entities WHERE domain = ?", (domain,))
    conn.execute("DELETE FROM relations WHERE domain = ?", (domain,))
    conn.execute("DELETE FROM documents WHERE domain = ?", (domain,))
    conn.commit()
    conn.close()


def clear_all():
    conn = get_connection()
    conn.execute("DELETE FROM entity_aliases")
    conn.execute("DELETE FROM canonical_entities")
    conn.execute("DELETE FROM entities")
    conn.execute("DELETE FROM relations")
    conn.execute("DELETE FROM documents")
    conn.commit()
    conn.close()


def link_domain_entities(domain, min_similarity=0.9):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, entity_type, source_file FROM entities WHERE domain = ? ORDER BY entity_type, name",
        (domain,),
    ).fetchall()

    conn.execute(
        "DELETE FROM entity_aliases WHERE canonical_id IN (SELECT id FROM canonical_entities WHERE domain = ?)",
        (domain,),
    )
    conn.execute("DELETE FROM canonical_entities WHERE domain = ?", (domain,))

    canonical_pool = {}
    linked_count = 0

    for row in rows:
        entity_id = row["id"]
        name = (row["name"] or "").strip()
        entity_type = (row["entity_type"] or "Other").strip()
        source_file = row["source_file"]
        normalized = normalize_name_for_match(name)
        if not normalized:
            continue

        type_key = entity_type.lower()
        if type_key not in canonical_pool:
            canonical_pool[type_key] = []

        chosen = choose_canonical(canonical_pool[type_key], normalized, min_similarity)
        if chosen is None:
            canonical_id = conn.execute(
                "INSERT INTO canonical_entities (domain, canonical_name, entity_type) VALUES (?, ?, ?)",
                (domain, name, entity_type),
            ).lastrowid
            chosen = {
                "canonical_id": canonical_id,
                "canonical_name": name,
                "normalized": normalized,
            }
            canonical_pool[type_key].append(chosen)
            confidence = 1.0
        else:
            confidence = name_similarity(normalized, chosen["normalized"])

        conn.execute(
            "INSERT INTO entity_aliases (entity_id, canonical_id, alias_name, confidence, source_file) VALUES (?, ?, ?, ?, ?)",
            (entity_id, chosen["canonical_id"], name, confidence, source_file),
        )
        linked_count += 1

    conn.commit()
    conn.close()
    return linked_count


def choose_canonical(candidates, normalized_name, min_similarity):
    best = None
    best_score = 0.0
    for candidate in candidates:
        score = name_similarity(normalized_name, candidate["normalized"])
        if score > best_score:
            best_score = score
            best = candidate
    if best is None or best_score < min_similarity:
        return None
    return best


def normalize_name_for_match(name):
    value = (name or "").strip().lower()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\b(incorporated|inc|ltd|llc|gmbh|ag|corp|corporation|co)\b", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def name_similarity(name_a, name_b):
    if not name_a or not name_b:
        return 0.0
    if name_a == name_b:
        return 1.0
    tokens_a = set(name_a.split())
    tokens_b = set(name_b.split())
    token_overlap = len(tokens_a.intersection(tokens_b)) / max(len(tokens_a.union(tokens_b)), 1)
    seq = SequenceMatcher(None, name_a, name_b).ratio()
    return (0.6 * seq) + (0.4 * token_overlap)
