"""Hybrid retrieval: FTS5 keyword search + sqlite-vec semantic search, fused
with reciprocal rank fusion. The MCP server (Slice 3) is a socket on top of
this module.

Deferred to Slice 5's demo experiment (A2): Qwen3's query-side instruction
prefix — one line in _vec_ranked, no re-embedding needed.
"""

from dataclasses import dataclass
from sqlite3 import Connection
from typing import Any

from cortex.core import embed

RRF_K = 60  # standard damping constant; tune only against Slice 5 numbers
CANDIDATES = 20  # depth fetched from each retriever before fusion


@dataclass
class Hit:
    chunk_id: int
    text: str
    source: str
    path: str
    score: float
    matched: list[str]  # which retrievers ranked it: "keyword", "semantic"


def search(
    conn: Connection,
    cfg: dict[str, Any],
    query: str,
    top_k: int = 5,
    embed_fn: embed.EmbedFn = embed.embed_texts,
) -> tuple[list[Hit], bool]:
    """Returns (hits, semantic_ok). semantic_ok False ⇒ Ollama unreachable or
    nothing embedded yet — results are keyword-only and the caller must say so."""
    fts_ids = _fts_ranked(conn, query)
    vec_ids, semantic_ok = _vec_ranked(conn, cfg, query, embed_fn)
    fused = rrf([fts_ids, vec_ids])
    ranked = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]
    hits = []
    for chunk_id, score in ranked:
        text, source, path = conn.execute(
            "SELECT c.text, d.source, d.path FROM chunks c"
            " JOIN documents d ON d.id = c.doc_id WHERE c.id = ?",
            (chunk_id,),
        ).fetchone()
        matched = [
            name
            for name, ids in (("keyword", fts_ids), ("semantic", vec_ids))
            if chunk_id in ids
        ]
        hits.append(Hit(chunk_id, text, source, path, score, matched))
    return hits, semantic_ok


def rrf(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """Reciprocal rank fusion: each list contributes 1/(k + rank) per item,
    summed — no score normalization across retrievers needed."""
    scores: dict[int, float] = {}
    for ids in rankings:
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def fts_query(query: str) -> str:
    """Quote every term so user input is never parsed as FTS5 syntax (AND,
    NEAR, *, unbalanced quotes). Terms are OR'd — bag-of-words with bm25
    ranking — so natural-language queries don't require every word to match."""
    terms = [t.replace('"', '""') for t in query.split()]
    return " OR ".join(f'"{t}"' for t in terms)


def _fts_ranked(conn: Connection, query: str) -> list[int]:
    match = fts_query(query)
    if not match:
        return []
    rows = conn.execute(
        "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
        (match, CANDIDATES),
    ).fetchall()
    return [row[0] for row in rows]


def _vec_ranked(
    conn: Connection, cfg: dict[str, Any], query: str, embed_fn: embed.EmbedFn
) -> tuple[list[int], bool]:
    if embed.check_model(conn, cfg["embed_model"]) is None:
        return [], False
    vectors = embed_fn(cfg["ollama_url"], cfg["embed_model"], [query])
    if vectors is None:
        return [], False
    rows = conn.execute(
        "SELECT chunk_id FROM chunk_vectors WHERE embedding MATCH ? AND k = ?"
        " ORDER BY distance",
        (embed.serialize(vectors[0]), CANDIDATES),
    ).fetchall()
    return [row[0] for row in rows], True
