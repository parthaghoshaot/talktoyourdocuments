import sqlite3
import os
import re
import json
import math
from difflib import SequenceMatcher
from config import DB_PATH, get_text_embedding


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

        CREATE TABLE IF NOT EXISTS content_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL,
            source_file_a TEXT NOT NULL,
            chunk_a INTEGER,
            source_file_b TEXT NOT NULL,
            chunk_b INTEGER,
            link_type TEXT NOT NULL,
            description TEXT,
            confidence REAL DEFAULT 1.0
        );

        CREATE TABLE IF NOT EXISTS entity_embeddings (
            entity_id INTEGER PRIMARY KEY,
            vector_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (entity_id) REFERENCES entities(id)
        );

        CREATE TABLE IF NOT EXISTS relation_embeddings (
            relation_id INTEGER PRIMARY KEY,
            vector_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (relation_id) REFERENCES relations(id)
        );

        CREATE INDEX IF NOT EXISTS idx_entities_domain ON entities(domain);
        CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
        CREATE INDEX IF NOT EXISTS idx_relations_domain ON relations(domain);
        CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject);
        CREATE INDEX IF NOT EXISTS idx_relations_object ON relations(object);
        CREATE INDEX IF NOT EXISTS idx_documents_domain ON documents(domain);
        CREATE INDEX IF NOT EXISTS idx_canonical_entities_domain ON canonical_entities(domain);
        CREATE INDEX IF NOT EXISTS idx_canonical_entities_name ON canonical_entities(canonical_name);
        CREATE INDEX IF NOT EXISTS idx_entity_aliases_canonical_id ON entity_aliases(canonical_id);
        CREATE INDEX IF NOT EXISTS idx_entity_aliases_alias_name ON entity_aliases(alias_name);
        CREATE INDEX IF NOT EXISTS idx_content_links_domain ON content_links(domain);
        CREATE INDEX IF NOT EXISTS idx_entity_embeddings_updated ON entity_embeddings(updated_at);
        CREATE INDEX IF NOT EXISTS idx_relation_embeddings_updated ON relation_embeddings(updated_at);

        CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
            name,
            name_translated,
            entity_type,
            description,
            description_translated,
            source_excerpt,
            domain,
            tokenize = 'unicode61'
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS relations_fts USING fts5(
            subject,
            subject_translated,
            predicate,
            object,
            object_translated,
            context,
            context_translated,
            source_excerpt,
            domain,
            tokenize = 'unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS entities_ai AFTER INSERT ON entities BEGIN
            INSERT INTO entities_fts(rowid, name, name_translated, entity_type, description, description_translated, source_excerpt, domain)
            VALUES (new.id, new.name, new.name_translated, new.entity_type, new.description, new.description_translated, new.source_excerpt, new.domain);
        END;

        CREATE TRIGGER IF NOT EXISTS entities_ad AFTER DELETE ON entities BEGIN
            DELETE FROM entities_fts WHERE rowid = old.id;
        END;

        CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities BEGIN
            UPDATE entities_fts
            SET name = new.name,
                name_translated = new.name_translated,
                entity_type = new.entity_type,
                description = new.description,
                description_translated = new.description_translated,
                source_excerpt = new.source_excerpt,
                domain = new.domain
            WHERE rowid = new.id;
        END;

        CREATE TRIGGER IF NOT EXISTS relations_ai AFTER INSERT ON relations BEGIN
            INSERT INTO relations_fts(rowid, subject, subject_translated, predicate, object, object_translated, context, context_translated, source_excerpt, domain)
            VALUES (new.id, new.subject, new.subject_translated, new.predicate, new.object, new.object_translated, new.context, new.context_translated, new.source_excerpt, new.domain);
        END;

        CREATE TRIGGER IF NOT EXISTS relations_ad AFTER DELETE ON relations BEGIN
            DELETE FROM relations_fts WHERE rowid = old.id;
        END;

        CREATE TRIGGER IF NOT EXISTS relations_au AFTER UPDATE ON relations BEGIN
            UPDATE relations_fts
            SET subject = new.subject,
                subject_translated = new.subject_translated,
                predicate = new.predicate,
                object = new.object,
                object_translated = new.object_translated,
                context = new.context,
                context_translated = new.context_translated,
                source_excerpt = new.source_excerpt,
                domain = new.domain
            WHERE rowid = new.id;
        END;
    """)
    ensure_column(conn, "entities", "source_chunk", "INTEGER")
    ensure_column(conn, "entities", "source_excerpt", "TEXT")
    ensure_column(conn, "entities", "source_page", "INTEGER")
    ensure_column(conn, "entities", "source_marker", "TEXT")
    ensure_column(conn, "entities", "confidence", "REAL DEFAULT 1.0")
    ensure_column(conn, "relations", "source_chunk", "INTEGER")
    ensure_column(conn, "relations", "source_excerpt", "TEXT")
    ensure_column(conn, "relations", "source_page", "INTEGER")
    ensure_column(conn, "relations", "source_marker", "TEXT")
    ensure_column(conn, "relations", "confidence", "REAL DEFAULT 1.0")

    ensure_fts_schema(conn)
    conn.execute(
        """
        INSERT INTO entities_fts(rowid, name, name_translated, entity_type, description, description_translated, source_excerpt, domain)
        SELECT e.id, e.name, e.name_translated, e.entity_type, e.description, e.description_translated, e.source_excerpt, e.domain
        FROM entities e
        WHERE NOT EXISTS (SELECT 1 FROM entities_fts f WHERE f.rowid = e.id)
        """
    )
    conn.execute(
        """
        INSERT INTO relations_fts(rowid, subject, subject_translated, predicate, object, object_translated, context, context_translated, source_excerpt, domain)
        SELECT r.id, r.subject, r.subject_translated, r.predicate, r.object, r.object_translated, r.context, r.context_translated, r.source_excerpt, r.domain
        FROM relations r
        WHERE NOT EXISTS (SELECT 1 FROM relations_fts f WHERE f.rowid = r.id)
        """
    )
    conn.commit()
    conn.close()


def ensure_fts_schema(conn):
    expected_entities_cols = [
        "name", "name_translated", "entity_type", "description",
        "description_translated", "source_excerpt", "domain",
    ]
    expected_relations_cols = [
        "subject", "subject_translated", "predicate", "object", "object_translated",
        "context", "context_translated", "source_excerpt", "domain",
    ]

    entities_cols = get_table_columns(conn, "entities_fts")
    relations_cols = get_table_columns(conn, "relations_fts")

    needs_reset = (
        entities_cols != expected_entities_cols
        or relations_cols != expected_relations_cols
    )

    if needs_reset:
        conn.executescript("""
            DROP TRIGGER IF EXISTS entities_ai;
            DROP TRIGGER IF EXISTS entities_ad;
            DROP TRIGGER IF EXISTS entities_au;
            DROP TRIGGER IF EXISTS relations_ai;
            DROP TRIGGER IF EXISTS relations_ad;
            DROP TRIGGER IF EXISTS relations_au;
            DROP TABLE IF EXISTS entities_fts;
            DROP TABLE IF EXISTS relations_fts;
        """)
        conn.executescript("""
            CREATE VIRTUAL TABLE entities_fts USING fts5(
                name,
                name_translated,
                entity_type,
                description,
                description_translated,
                source_excerpt,
                domain,
                tokenize = 'unicode61'
            );

            CREATE VIRTUAL TABLE relations_fts USING fts5(
                subject,
                subject_translated,
                predicate,
                object,
                object_translated,
                context,
                context_translated,
                source_excerpt,
                domain,
                tokenize = 'unicode61'
            );

            CREATE TRIGGER entities_ai AFTER INSERT ON entities BEGIN
                INSERT INTO entities_fts(rowid, name, name_translated, entity_type, description, description_translated, source_excerpt, domain)
                VALUES (new.id, new.name, new.name_translated, new.entity_type, new.description, new.description_translated, new.source_excerpt, new.domain);
            END;

            CREATE TRIGGER entities_ad AFTER DELETE ON entities BEGIN
                DELETE FROM entities_fts WHERE rowid = old.id;
            END;

            CREATE TRIGGER entities_au AFTER UPDATE ON entities BEGIN
                UPDATE entities_fts
                SET name = new.name,
                    name_translated = new.name_translated,
                    entity_type = new.entity_type,
                    description = new.description,
                    description_translated = new.description_translated,
                    source_excerpt = new.source_excerpt,
                    domain = new.domain
                WHERE rowid = new.id;
            END;

            CREATE TRIGGER relations_ai AFTER INSERT ON relations BEGIN
                INSERT INTO relations_fts(rowid, subject, subject_translated, predicate, object, object_translated, context, context_translated, source_excerpt, domain)
                VALUES (new.id, new.subject, new.subject_translated, new.predicate, new.object, new.object_translated, new.context, new.context_translated, new.source_excerpt, new.domain);
            END;

            CREATE TRIGGER relations_ad AFTER DELETE ON relations BEGIN
                DELETE FROM relations_fts WHERE rowid = old.id;
            END;

            CREATE TRIGGER relations_au AFTER UPDATE ON relations BEGIN
                UPDATE relations_fts
                SET subject = new.subject,
                    subject_translated = new.subject_translated,
                    predicate = new.predicate,
                    object = new.object,
                    object_translated = new.object_translated,
                    context = new.context,
                    context_translated = new.context_translated,
                    source_excerpt = new.source_excerpt,
                    domain = new.domain
                WHERE rowid = new.id;
            END;
        """)


def get_table_columns(conn, table_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row[1] for row in rows]


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
        "INSERT INTO entities (name, name_translated, entity_type, description, description_translated, source_chunk, source_excerpt, source_page, source_marker, confidence, language, domain, source_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            e.get("confidence", 1.0),
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
        "INSERT INTO relations (subject, subject_translated, predicate, object, object_translated, context, context_translated, source_chunk, source_excerpt, source_page, source_marker, confidence, language, domain, source_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            r.get("confidence", 1.0),
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
    merged = {}

    fts_query = to_fts_query(query)
    if fts_query:
        if domain:
            fts_rows = conn.execute(
                """
                SELECT e.*
                FROM entities_fts f
                JOIN entities e ON e.id = f.rowid
                WHERE entities_fts MATCH ? AND e.domain = ?
                ORDER BY bm25(entities_fts)
                LIMIT 100
                """,
                (fts_query, domain),
            ).fetchall()
        else:
            fts_rows = conn.execute(
                """
                SELECT e.*
                FROM entities_fts f
                JOIN entities e ON e.id = f.rowid
                WHERE entities_fts MATCH ?
                ORDER BY bm25(entities_fts)
                LIMIT 100
                """,
                (fts_query,),
            ).fetchall()
        for row in fts_rows:
            merged[row["id"]] = dict(row)

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

    for row in rows:
        merged[row["id"]] = dict(row)

    conn.close()
    return list(merged.values())


def search_relations(query, domain=None):
    conn = get_connection()
    q = f"%{query}%"
    merged = {}

    fts_query = to_fts_query(query)
    if fts_query:
        if domain:
            fts_rows = conn.execute(
                """
                SELECT r.*
                FROM relations_fts f
                JOIN relations r ON r.id = f.rowid
                WHERE relations_fts MATCH ? AND r.domain = ?
                ORDER BY bm25(relations_fts)
                LIMIT 120
                """,
                (fts_query, domain),
            ).fetchall()
        else:
            fts_rows = conn.execute(
                """
                SELECT r.*
                FROM relations_fts f
                JOIN relations r ON r.id = f.rowid
                WHERE relations_fts MATCH ?
                ORDER BY bm25(relations_fts)
                LIMIT 120
                """,
                (fts_query,),
            ).fetchall()
        for row in fts_rows:
            merged[row["id"]] = dict(row)

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

    for row in rows:
        merged[row["id"]] = dict(row)

    conn.close()
    return list(merged.values())


def semantic_search_entities(query, domain=None, top_k=25):
    query_vector = get_text_embedding(query)
    if not query_vector:
        return []

    backfill_missing_embeddings("entity", domain=domain, limit=120)
    conn = get_connection()
    if domain:
        rows = conn.execute(
            """
            SELECT e.*, ee.vector_json
            FROM entities e
            JOIN entity_embeddings ee ON ee.entity_id = e.id
            WHERE e.domain = ?
            LIMIT 900
            """,
            (domain,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT e.*, ee.vector_json
            FROM entities e
            JOIN entity_embeddings ee ON ee.entity_id = e.id
            LIMIT 900
            """
        ).fetchall()
    conn.close()

    scored = []
    for row in rows:
        candidate = json_to_vector(row["vector_json"])
        sim = cosine_similarity(query_vector, candidate)
        if sim <= 0.12:
            continue
        payload = dict(row)
        payload.pop("vector_json", None)
        payload["semantic_score"] = sim
        scored.append((sim, payload))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def semantic_search_relations(query, domain=None, top_k=30):
    query_vector = get_text_embedding(query)
    if not query_vector:
        return []

    backfill_missing_embeddings("relation", domain=domain, limit=160)
    conn = get_connection()
    if domain:
        rows = conn.execute(
            """
            SELECT r.*, re.vector_json
            FROM relations r
            JOIN relation_embeddings re ON re.relation_id = r.id
            WHERE r.domain = ?
            LIMIT 1200
            """,
            (domain,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT r.*, re.vector_json
            FROM relations r
            JOIN relation_embeddings re ON re.relation_id = r.id
            LIMIT 1200
            """
        ).fetchall()
    conn.close()

    scored = []
    for row in rows:
        candidate = json_to_vector(row["vector_json"])
        sim = cosine_similarity(query_vector, candidate)
        if sim <= 0.12:
            continue
        payload = dict(row)
        payload.pop("vector_json", None)
        payload["semantic_score"] = sim
        scored.append((sim, payload))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]


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


def store_content_links(links, domain):
    if not links:
        return
    conn = get_connection()
    conn.executemany(
        "INSERT INTO content_links (domain, source_file_a, chunk_a, source_file_b, chunk_b, link_type, description, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(domain, l["file_a"], l.get("chunk_a"), l["file_b"], l.get("chunk_b"),
          l["link_type"], l.get("description", ""), l.get("confidence", 1.0)) for l in links]
    )
    conn.commit()
    conn.close()


def get_content_links(domain=None):
    conn = get_connection()
    if domain:
        rows = conn.execute("SELECT * FROM content_links WHERE domain = ?", (domain,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM content_links").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_domain(domain):
    conn = get_connection()
    conn.execute(
        "DELETE FROM entity_embeddings WHERE entity_id IN (SELECT id FROM entities WHERE domain = ?)",
        (domain,),
    )
    conn.execute(
        "DELETE FROM relation_embeddings WHERE relation_id IN (SELECT id FROM relations WHERE domain = ?)",
        (domain,),
    )
    conn.execute(
        "DELETE FROM entity_aliases WHERE canonical_id IN (SELECT id FROM canonical_entities WHERE domain = ?)",
        (domain,),
    )
    conn.execute("DELETE FROM canonical_entities WHERE domain = ?", (domain,))
    conn.execute("DELETE FROM content_links WHERE domain = ?", (domain,))
    conn.execute("DELETE FROM entities WHERE domain = ?", (domain,))
    conn.execute("DELETE FROM relations WHERE domain = ?", (domain,))
    conn.execute("DELETE FROM documents WHERE domain = ?", (domain,))
    conn.commit()
    conn.close()


def clear_all():
    conn = get_connection()
    conn.execute("DELETE FROM entity_embeddings")
    conn.execute("DELETE FROM relation_embeddings")
    conn.execute("DELETE FROM entity_aliases")
    conn.execute("DELETE FROM canonical_entities")
    conn.execute("DELETE FROM content_links")
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


def expand_query_terms(terms, domain=None, max_expansions_per_term=8):
    conn = get_connection()
    expanded = set()

    for term in terms:
        clean = (term or "").strip()
        if not clean:
            continue
        expanded.add(clean)
        q = f"%{clean}%"

        if domain:
            alias_rows = conn.execute(
                """
                SELECT DISTINCT ea.alias_name AS value
                FROM entity_aliases ea
                JOIN canonical_entities ce ON ce.id = ea.canonical_id
                WHERE ce.domain = ? AND ea.alias_name LIKE ?
                LIMIT ?
                """,
                (domain, q, max_expansions_per_term),
            ).fetchall()
            canonical_rows = conn.execute(
                """
                SELECT DISTINCT ce.canonical_name AS value
                FROM canonical_entities ce
                WHERE ce.domain = ? AND ce.canonical_name LIKE ?
                LIMIT ?
                """,
                (domain, q, max_expansions_per_term),
            ).fetchall()
        else:
            alias_rows = conn.execute(
                """
                SELECT DISTINCT alias_name AS value
                FROM entity_aliases
                WHERE alias_name LIKE ?
                LIMIT ?
                """,
                (q, max_expansions_per_term),
            ).fetchall()
            canonical_rows = conn.execute(
                """
                SELECT DISTINCT canonical_name AS value
                FROM canonical_entities
                WHERE canonical_name LIKE ?
                LIMIT ?
                """,
                (q, max_expansions_per_term),
            ).fetchall()

        for row in alias_rows:
            value = (row["value"] or "").strip()
            if value:
                expanded.add(value)
        for row in canonical_rows:
            value = (row["value"] or "").strip()
            if value:
                expanded.add(value)

    conn.close()
    return sorted(expanded)


def get_neighbor_relations(entity_names, domain=None, max_rows=200):
    names = [n.strip() for n in entity_names if (n or "").strip()]
    if not names:
        return []

    conn = get_connection()
    placeholders = ",".join(["?"] * len(names))
    base_query = (
        f"SELECT * FROM relations WHERE (subject IN ({placeholders}) OR object IN ({placeholders}))"
    )
    params = list(names) + list(names)

    if domain:
        base_query += " AND domain = ?"
        params.append(domain)

    base_query += " ORDER BY confidence DESC LIMIT ?"
    params.append(max_rows)

    rows = conn.execute(base_query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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


def to_fts_query(query):
    tokens = re.findall(r"[a-zA-Z0-9_]+", (query or "").lower())
    tokens = [t for t in tokens if len(t) > 2]
    if not tokens:
        return ""
    return " OR ".join([f'{token}*' for token in tokens])


def backfill_missing_embeddings(kind, domain=None, limit=100):
    conn = get_connection()
    if kind == "entity":
        if domain:
            rows = conn.execute(
                """
                SELECT e.id, e.name, e.description, e.source_excerpt
                FROM entities e
                LEFT JOIN entity_embeddings ee ON ee.entity_id = e.id
                WHERE ee.entity_id IS NULL AND e.domain = ?
                LIMIT ?
                """,
                (domain, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT e.id, e.name, e.description, e.source_excerpt
                FROM entities e
                LEFT JOIN entity_embeddings ee ON ee.entity_id = e.id
                WHERE ee.entity_id IS NULL
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        for row in rows:
            text = build_entity_embedding_text(dict(row))
            vector = get_text_embedding(text)
            if not vector:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO entity_embeddings (entity_id, vector_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (row["id"], vector_to_json(vector)),
            )

    elif kind == "relation":
        if domain:
            rows = conn.execute(
                """
                SELECT r.id, r.subject, r.predicate, r.object, r.context, r.source_excerpt
                FROM relations r
                LEFT JOIN relation_embeddings re ON re.relation_id = r.id
                WHERE re.relation_id IS NULL AND r.domain = ?
                LIMIT ?
                """,
                (domain, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT r.id, r.subject, r.predicate, r.object, r.context, r.source_excerpt
                FROM relations r
                LEFT JOIN relation_embeddings re ON re.relation_id = r.id
                WHERE re.relation_id IS NULL
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        for row in rows:
            text = build_relation_embedding_text(dict(row))
            vector = get_text_embedding(text)
            if not vector:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO relation_embeddings (relation_id, vector_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (row["id"], vector_to_json(vector)),
            )

    conn.commit()
    conn.close()


def build_entity_embedding_text(entity):
    return " | ".join([
        str(entity.get("name", "")),
        str(entity.get("description", "")),
        str(entity.get("source_excerpt", ""))[:300],
    ]).strip()


def build_relation_embedding_text(relation):
    edge = f"{relation.get('subject', '')} {relation.get('predicate', '')} {relation.get('object', '')}"
    return " | ".join([
        edge,
        str(relation.get("context", "")),
        str(relation.get("source_excerpt", ""))[:300],
    ]).strip()


def vector_to_json(vector):
    return json.dumps([float(v) for v in vector], separators=(",", ":"))


def json_to_vector(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return [float(v) for v in parsed]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def cosine_similarity(vec_a, vec_b):
    if not vec_a or not vec_b:
        return 0.0
    if len(vec_a) != len(vec_b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
