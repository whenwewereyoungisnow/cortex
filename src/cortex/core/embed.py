"""Embeddings via Ollama's /api/embed, plus the ingest-time backlog worker.

Degradation contract: Ollama being down never fails an ingest — chunks keep
their needs_embedding flag and the next refresh catches up the backlog.
Vectors live in a sqlite-vec vec0 table (chunk_vectors) created lazily once
the model's dimension is known from the first response, never hardcoded.
"""

import struct
from collections.abc import Callable
from sqlite3 import Connection
from typing import Any

import httpx

BATCH_SIZE = 32

EmbedFn = Callable[[str, str, list[str]], list[list[float]] | None]


def embed_texts(url: str, model: str, texts: list[str]) -> list[list[float]] | None:
    """One batched /api/embed call. None ⇒ Ollama unreachable or erroring —
    callers degrade instead of crashing."""
    try:
        resp = httpx.post(
            f"{url}/api/embed",
            json={"model": model, "input": texts},
            timeout=120.0,  # first request loads the model into memory (5-20s)
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    return resp.json()["embeddings"]


def serialize(vector: list[float]) -> bytes:
    """Pack as float32 — the raw layout vec0 expects."""
    return struct.pack(f"{len(vector)}f", *vector)


def embed_backlog(
    conn: Connection, cfg: dict[str, Any], embed_fn: EmbedFn = embed_texts
) -> tuple[int, int]:
    """Embed every chunk flagged needs_embedding; returns (embedded, remaining).
    remaining > 0 means Ollama went away mid-run — flags stay set for next time.
    Also prunes stale vectors first (FTS has triggers for this; the vec0 table
    can't, since it may not exist yet): a vector survives only if its chunk
    exists AND is marked embedded — deleted chunks lose theirs, and re-chunked
    documents can reuse rowids of deleted chunks, so a flagged chunk's old
    vector is stale by definition."""
    if stored_meta(conn) is not None:
        with conn:
            conn.execute(
                "DELETE FROM chunk_vectors WHERE chunk_id NOT IN"
                " (SELECT id FROM chunks WHERE needs_embedding = 0)"
            )
    rows = conn.execute(
        "SELECT id, text FROM chunks WHERE needs_embedding = 1 ORDER BY id"
    ).fetchall()
    done = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        vectors = embed_fn(cfg["ollama_url"], cfg["embed_model"], [t for _, t in batch])
        if vectors is None:
            break
        _ensure_vec_table(conn, cfg["embed_model"], len(vectors[0]))
        with conn:  # vector insert + flag clear are atomic per batch
            conn.executemany(
                "INSERT INTO chunk_vectors (chunk_id, embedding) VALUES (?, ?)",
                [(cid, serialize(v)) for (cid, _), v in zip(batch, vectors, strict=True)],
            )
            conn.executemany(
                "UPDATE chunks SET needs_embedding = 0 WHERE id = ?",
                [(cid,) for cid, _ in batch],
            )
        done += len(batch)
    return done, len(rows) - done


def backlog_count(conn: Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE needs_embedding = 1"
    ).fetchone()[0]


def stored_meta(conn: Connection) -> tuple[str, int] | None:
    """(model, dim) the index was embedded with, or None if nothing embedded yet."""
    row = conn.execute("SELECT model, dim FROM embedding_meta WHERE id = 1").fetchone()
    return (row[0], row[1]) if row else None


def check_model(conn: Connection, model: str) -> tuple[str, int] | None:
    """Fail loudly if config's embed model no longer matches the index —
    comparing vectors from different models is silently meaningless."""
    meta = stored_meta(conn)
    if meta is not None and meta[0] != model:
        raise RuntimeError(
            f"index was embedded with {meta[0]} but config.toml now says {model}"
            " — delete the DB and re-run `cortex ingest`"
        )
    return meta


def _ensure_vec_table(conn: Connection, model: str, dim: int) -> None:
    if check_model(conn, model) is not None:
        return
    with conn:
        conn.execute(
            "INSERT INTO embedding_meta (id, model, dim) VALUES (1, ?, ?)", (model, dim)
        )
        conn.execute(
            "CREATE VIRTUAL TABLE chunk_vectors USING"
            f" vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{int(dim)}])"
        )
