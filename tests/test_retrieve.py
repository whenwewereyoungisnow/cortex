"""Hybrid retrieval: RRF fusion, FTS escaping, trigger sync, and the
Ollama-down degradation path. No test here talks to a real Ollama — the
embedder is injected."""

import pytest

from cortex.core import db, embed, ingest, retrieve

# Deterministic 4-dim "embeddings": one axis per topic word. Texts sharing a
# topic word get identical vectors, so nearest-neighbor is predictable.
TOPICS = ("railway", "ollama", "sqlite", "python")


def fake_embed(url, model, texts):
    return [[float(w in t.lower()) for w in TOPICS] for t in texts]


def down_embed(url, model, texts):
    return None  # what embed_texts returns when Ollama is unreachable


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "railway.md").write_text(
        "# Railway deploys\n\nRailway shared variables differ from service variables.\n"
    )
    (root / "ollama.md").write_text(
        "# Ollama quirks\n\nThe think flag is top-level, not inside options.\n"
    )
    (root / "mcp.md").write_text(
        "# MCP setup\n\nRegister with `claude mcp add cortex -- uv run cortex-mcp`.\n"
    )
    conn = db.connect(tmp_path / "test.db")
    cfg = {
        "embed_model": "fake-model",
        "ollama_url": "http://localhost:0",
        "chunking": {"target_chars": 1000, "overlap_chars": 150},
        "sources": [{"name": "test", "path": root}],
    }
    ingest.sync(conn, cfg)
    yield conn, cfg, root
    conn.close()


def test_rrf_rewards_agreement():
    fused = retrieve.rrf([[1, 2, 3], [2, 4]])
    assert fused[2] > fused[1]  # ranked by both lists beats a single first place
    assert fused[1] > fused[3]
    assert set(fused) == {1, 2, 3, 4}


def test_fts_query_neutralizes_operators():
    assert retrieve.fts_query("a AND b") == '"a" OR "AND" OR "b"'
    assert retrieve.fts_query('say "hi"') == '"say" OR """hi"""'
    assert retrieve.fts_query("") == ""


def test_hybrid_search_finds_expected_doc(corpus):
    conn, cfg, _ = corpus
    done, remaining = embed.embed_backlog(conn, cfg, embed_fn=fake_embed)
    assert done > 0 and remaining == 0
    hits, semantic_ok = retrieve.search(conn, cfg, "railway variables", embed_fn=fake_embed)
    assert semantic_ok
    assert hits[0].path == "railway.md"
    assert hits[0].source == "test"
    assert set(hits[0].matched) == {"keyword", "semantic"}
    assert hits[0].score > 0


def test_exact_identifier_found_by_keyword(corpus):
    conn, cfg, _ = corpus
    embed.embed_backlog(conn, cfg, embed_fn=fake_embed)
    # "cortex-mcp" is outside the fake embedding vocabulary — only FTS can find it
    hits, _ = retrieve.search(conn, cfg, "cortex-mcp", embed_fn=fake_embed)
    assert hits and hits[0].path == "mcp.md"
    assert "keyword" in hits[0].matched


def test_ollama_down_degrades_to_keyword_only(corpus):
    conn, cfg, _ = corpus
    done, remaining = embed.embed_backlog(conn, cfg, embed_fn=down_embed)
    assert done == 0 and remaining == embed.backlog_count(conn) > 0
    hits, semantic_ok = retrieve.search(conn, cfg, "railway", embed_fn=down_embed)
    assert not semantic_ok
    assert hits and hits[0].path == "railway.md"  # FTS still answers


def test_backlog_caught_up_after_recovery(corpus):
    conn, cfg, _ = corpus
    embed.embed_backlog(conn, cfg, embed_fn=down_embed)  # outage: flags stay set
    done, remaining = embed.embed_backlog(conn, cfg, embed_fn=fake_embed)
    assert done > 0 and remaining == 0
    assert embed.backlog_count(conn) == 0
    _, semantic_ok = retrieve.search(conn, cfg, "railway", embed_fn=fake_embed)
    assert semantic_ok


def test_changed_doc_reembeds_without_orphan_vectors(corpus):
    conn, cfg, root = corpus
    embed.embed_backlog(conn, cfg, embed_fn=fake_embed)
    (root / "railway.md").write_text("# Railway deploys\n\nEntirely new railway text.\n")
    ingest.sync(conn, cfg)
    assert embed.backlog_count(conn) > 0  # fresh chunks are flagged again
    embed.embed_backlog(conn, cfg, embed_fn=fake_embed)
    vectors = conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert vectors == chunks


def test_fts_stays_in_sync_on_delete(corpus):
    conn, cfg, root = corpus
    (root / "railway.md").unlink()
    ingest.sync(conn, cfg)
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    fts = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    assert fts == chunks
    hits, _ = retrieve.search(conn, cfg, "railway", embed_fn=down_embed)
    assert all(h.path != "railway.md" for h in hits)


def test_model_mismatch_fails_loudly(corpus):
    conn, cfg, _ = corpus
    embed.embed_backlog(conn, cfg, embed_fn=fake_embed)
    cfg["embed_model"] = "different-model"
    with pytest.raises(RuntimeError, match="delete the DB"):
        retrieve.search(conn, cfg, "railway", embed_fn=fake_embed)
