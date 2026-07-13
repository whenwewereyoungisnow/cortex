"""Ingestion sync: idempotency, change/delete handling, and the load-bearing
gitignore-style exclusion semantics (D3 safety)."""

from pathlib import Path, PurePosixPath

import pytest

from cortex.core import db, ingest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "src"
    (root / "notes").mkdir(parents=True)
    for f in FIXTURES.glob("*.md"):
        (root / "notes" / f.name).write_text(f.read_text())
    # structural junk that must never enter the corpus
    for junk in (
        "somerepo/node_modules/pkg",
        "somerepo/data",
        "somerepo/.git",
        "somerepo/.venv/lib/site-packages/pkg",
        "somerepo/tests/fixtures",
        "transcripts",
    ):
        d = root / junk
        d.mkdir(parents=True)
        (d / "junk.md").write_text("# should never be ingested\n")
    (root / "somerepo" / "README.md").write_text("# Somerepo\n\nReal repo docs.\n")
    conn = db.connect(tmp_path / "test.db")
    cfg = {
        "chunking": {"target_chars": 1000, "overlap_chars": 150},
        "sources": [{"name": "test", "path": root}],
    }
    yield conn, cfg, root
    conn.close()


def _doc_paths(conn):
    return {row[0] for row in conn.execute("SELECT path FROM documents")}


def test_ingest_counts_and_nested_exclusions(corpus):
    conn, cfg, root = corpus
    stats = ingest.sync(conn, cfg)["test"]
    assert stats.added == 3  # learnings.md, plain.md, somerepo/README.md
    paths = _doc_paths(conn)
    assert paths == {"notes/learnings.md", "notes/plain.md", "somerepo/README.md"}
    # load-bearing: nested junk excluded even though patterns have no leading **/
    assert "somerepo/node_modules/pkg/junk.md" not in paths
    assert "somerepo/data/junk.md" not in paths
    assert "somerepo/.venv/lib/site-packages/pkg/junk.md" not in paths
    assert "somerepo/tests/fixtures/junk.md" not in paths


def test_gitignore_style_matching():
    m = ingest._matches
    assert m(PurePosixPath("somerepo/node_modules/foo.md"), ["node_modules/**"])
    assert m(PurePosixPath("data/x.md"), ["data/**"])
    assert m(PurePosixPath("a/b/data/x.md"), ["data/**"])
    assert not m(PurePosixPath("docs/data.md"), ["data/**"])  # file named data.md is fine
    assert m(PurePosixPath("note.icloud"), ["**/*.icloud"])
    assert m(PurePosixPath("a/.note.md.icloud"), ["**/*.icloud"])
    assert m(PurePosixPath("docs/readme.md"), ["**/*.md"])
    # hidden-dir rule: any dot-directory at any depth
    assert m(PurePosixPath("repo/.venv/lib/x.md"), [".*/**"])
    assert m(PurePosixPath(".pytest_cache/README.md"), [".*/**"])
    assert not m(PurePosixPath("docs/guide.md"), [".*/**"])


def test_frontmatter_and_wikilinks_cleaned_in_chunks(corpus):
    conn, cfg, _ = corpus
    ingest.sync(conn, cfg)
    texts = [row[0] for row in conn.execute("SELECT text FROM chunks")]
    assert texts
    assert all("tags:" not in t for t in texts)  # no YAML frontmatter as prose
    assert all("[[" not in t for t in texts)
    assert any("Railway Gotchas" in t for t in texts)  # wikilink text kept as prose
    row = conn.execute(
        "SELECT metadata FROM documents WHERE path = 'notes/learnings.md'"
    ).fetchone()
    assert "railway" in row[0]  # frontmatter landed in metadata JSON


def test_reingest_is_idempotent(corpus):
    conn, cfg, _ = corpus
    ingest.sync(conn, cfg)
    before = ingest.corpus_stats(conn)
    stats = ingest.sync(conn, cfg)["test"]
    assert (stats.added, stats.changed, stats.deleted) == (0, 0, 0)
    assert ingest.corpus_stats(conn) == before


def test_changed_file_rechunks_only_that_document(corpus):
    conn, cfg, root = corpus
    ingest.sync(conn, cfg)
    untouched_before = conn.execute(
        "SELECT c.id FROM chunks c JOIN documents d ON d.id = c.doc_id"
        " WHERE d.path = 'notes/learnings.md' ORDER BY c.seq"
    ).fetchall()
    (root / "notes" / "plain.md").write_text("# Plain note\n\nCompletely new body.\n")
    stats = ingest.sync(conn, cfg)["test"]
    assert (stats.added, stats.changed, stats.deleted) == (0, 1, 0)
    untouched_after = conn.execute(
        "SELECT c.id FROM chunks c JOIN documents d ON d.id = c.doc_id"
        " WHERE d.path = 'notes/learnings.md' ORDER BY c.seq"
    ).fetchall()
    assert untouched_after == untouched_before
    new_texts = [
        row[0]
        for row in conn.execute(
            "SELECT c.text FROM chunks c JOIN documents d ON d.id = c.doc_id"
            " WHERE d.path = 'notes/plain.md'"
        )
    ]
    assert new_texts and all("Completely new body" in t for t in new_texts)


def test_deleted_file_pruned(corpus):
    conn, cfg, root = corpus
    ingest.sync(conn, cfg)
    (root / "notes" / "plain.md").unlink()
    stats = ingest.sync(conn, cfg)["test"]
    assert stats.deleted == 1
    assert "notes/plain.md" not in _doc_paths(conn)
    orphans = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE doc_id NOT IN (SELECT id FROM documents)"
    ).fetchone()[0]
    assert orphans == 0


def test_single_file_source(tmp_path):
    target = tmp_path / "CLAUDE.md"
    target.write_text("# Setup\n\nGlobal machine setup notes.\n")
    conn = db.connect(tmp_path / "test.db")
    cfg = {"sources": [{"name": "setup-docs", "path": target}]}
    stats = ingest.sync(conn, cfg)["setup-docs"]
    assert stats.added == 1
    assert _doc_paths(conn) == {"CLAUDE.md"}
    conn.close()


def test_non_utf8_skipped_without_crash(corpus):
    conn, cfg, root = corpus
    (root / "notes" / "bad.md").write_bytes(b"\xff\xfe not really text")
    stats = ingest.sync(conn, cfg)["test"]
    assert stats.skipped == 1
    assert stats.added == 3
    assert "notes/bad.md" not in _doc_paths(conn)


def test_missing_source_is_not_pruned(corpus, tmp_path):
    conn, cfg, root = corpus
    ingest.sync(conn, cfg)
    docs_before = _doc_paths(conn)
    root.rename(tmp_path / "gone")
    stats = ingest.sync(conn, cfg)["test"]
    assert stats.missing is True
    assert stats.deleted == 0
    assert _doc_paths(conn) == docs_before  # an unmounted source must not empty the index
