"""SQLite store: schema + connection. Files on disk are canonical; this DB is
a disposable index that can be deleted and rebuilt at any time."""

import sqlite3
from pathlib import Path

import sqlite_vec

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL REFERENCES sources(name),
    path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    mtime REAL NOT NULL,
    metadata TEXT,
    ingested_at TEXT NOT NULL,
    UNIQUE (source, path)
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    needs_embedding INTEGER NOT NULL DEFAULT 1,
    UNIQUE (doc_id, seq)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id'
);

-- Triggers keep the FTS index in sync on both deletion paths: explicit
-- DELETE FROM chunks and the documents -> chunks ON DELETE CASCADE.
-- Chunks are never UPDATEd (changed file => delete + reinsert).
CREATE TRIGGER IF NOT EXISTS chunks_fts_insert AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts (rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_delete AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TABLE IF NOT EXISTS ingest_log (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    added INTEGER NOT NULL DEFAULT 0,
    changed INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS embedding_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    model TEXT NOT NULL,
    dim INTEGER NOT NULL
);
"""
# The chunk_vectors vec0 table is NOT in SCHEMA: its dimension comes from the
# first embedding response (never hardcoded), so core/embed.py creates it
# lazily and records model + dim in embedding_meta.


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _reject_pre_slice2_db(conn)
    conn.executescript(SCHEMA)
    return conn


def _reject_pre_slice2_db(conn: sqlite3.Connection) -> None:
    """No migrations by design (A1): a DB from before the Slice 2 schema must
    be deleted and rebuilt, not silently half-upgraded by IF NOT EXISTS."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(chunks)")}
    if cols and "needs_embedding" not in cols:
        raise RuntimeError(
            "cortex.db predates the Slice 2 schema — delete it and re-run"
            " `cortex ingest` (files on disk are canonical; the DB is disposable)"
        )
