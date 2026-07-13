"""Walk allowlisted sources and sync documents + chunks into SQLite.

Glob semantics are gitignore-style: a pattern without a leading '/' matches at
any depth, so 'data/**' also excludes 'somerepo/data/...'. This is load-bearing
for D3's safety model — every repo's data/, .git/ and node_modules/ must stay
out of the corpus. tests/test_ingest.py pins this behavior.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from sqlite3 import Connection
from typing import Any

from cortex.core.chunk import chunk, clean_markdown

DEFAULT_INCLUDE = ["**/*.md"]
DEFAULT_EXCLUDE = [
    ".*/**",  # any dot-directory: .obsidian, .git, .venv, .pytest_cache, .claude, ...
    "node_modules/**",
    "venv/**",
    "data/**",
    "transcripts/**",
    "tests/fixtures/**",
    "**/*.icloud",
]


@dataclass
class SourceStats:
    added: int = 0
    changed: int = 0
    deleted: int = 0
    skipped: int = 0
    missing: bool = False


def sync(conn: Connection, cfg: dict[str, Any]) -> dict[str, SourceStats]:
    """One shared routine for both `ingest` and `refresh`: walk every source,
    act only on new/changed/deleted files."""
    chunking = cfg.get("chunking", {})
    target = chunking.get("target_chars", 1000)
    overlap = chunking.get("overlap_chars", 150)
    with conn:
        log_id = conn.execute(
            "INSERT INTO ingest_log (started_at) VALUES (?)",
            (_now(),),
        ).lastrowid

    results: dict[str, SourceStats] = {}
    try:
        for source in cfg["sources"]:
            results[source["name"]] = _sync_source(conn, source, target, overlap)
    except Exception:
        with conn:
            conn.execute(
                "UPDATE ingest_log SET finished_at = ?, status = 'failed' WHERE id = ?",
                (_now(), log_id),
            )
        raise

    stats = list(results.values())
    with conn:
        conn.execute(
            "UPDATE ingest_log SET finished_at = ?, added = ?, changed = ?,"
            " deleted = ?, skipped = ?, status = 'ok' WHERE id = ?",
            (
                _now(),
                sum(s.added for s in stats),
                sum(s.changed for s in stats),
                sum(s.deleted for s in stats),
                sum(s.skipped for s in stats),
                log_id,
            ),
        )
    return results


def corpus_stats(conn: Connection) -> list[tuple[str, int, int]]:
    """(source, docs, chunks) per source."""
    return conn.execute(
        "SELECT d.source, COUNT(DISTINCT d.id), COUNT(c.id)"
        " FROM documents d LEFT JOIN chunks c ON c.doc_id = d.id"
        " GROUP BY d.source ORDER BY d.source"
    ).fetchall()


def _sync_source(
    conn: Connection, source: dict[str, Any], target: int, overlap: int
) -> SourceStats:
    stats = SourceStats()
    name, root = source["name"], source["path"]
    if not root.exists():
        # Never prune documents of a missing source: an unmounted or
        # iCloud-evicted folder must not silently empty the index.
        print(f"warning: source {name}: {root} does not exist — skipped")
        stats.missing = True
        return stats

    with conn:
        conn.execute(
            "INSERT INTO sources (name, path) VALUES (?, ?)"
            " ON CONFLICT(name) DO UPDATE SET path = excluded.path",
            (name, str(root)),
        )

    if root.is_file():
        files: dict[str, Path] = {root.name: root}
    else:
        include = source.get("include", DEFAULT_INCLUDE)
        exclude = source.get("exclude", DEFAULT_EXCLUDE)
        files = dict(_walk_source(root, include, exclude))

    for rel, abs_path in files.items():
        _sync_file(conn, name, rel, abs_path, target, overlap, stats)

    stored = [row[0] for row in conn.execute("SELECT path FROM documents WHERE source = ?", (name,))]
    for path in stored:
        if path not in files:
            with conn:
                conn.execute("DELETE FROM documents WHERE source = ? AND path = ?", (name, path))
            stats.deleted += 1
    return stats


def _sync_file(
    conn: Connection,
    source: str,
    rel: str,
    abs_path: Path,
    target: int,
    overlap: int,
    stats: SourceStats,
) -> None:
    try:
        raw = abs_path.read_bytes()
    except OSError as e:
        print(f"warning: {source}/{rel}: unreadable ({e}) — skipped")
        stats.skipped += 1
        return
    digest = hashlib.sha256(raw).hexdigest()
    row = conn.execute(
        "SELECT id, content_hash FROM documents WHERE source = ? AND path = ?",
        (source, rel),
    ).fetchone()
    if row and row[1] == digest:
        return
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        print(f"warning: {source}/{rel}: not valid UTF-8 — skipped")
        stats.skipped += 1
        return

    metadata, cleaned = clean_markdown(text)
    chunks = chunk(cleaned, target=target, overlap=overlap)
    meta_json = json.dumps(metadata, default=str) if metadata else None
    mtime = abs_path.stat().st_mtime

    with conn:  # changed file ⇒ delete + reinsert its chunks in one transaction
        if row:
            doc_id = row[0]
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "UPDATE documents SET content_hash = ?, mtime = ?, metadata = ?,"
                " ingested_at = ? WHERE id = ?",
                (digest, mtime, meta_json, _now(), doc_id),
            )
            stats.changed += 1
        else:
            doc_id = conn.execute(
                "INSERT INTO documents (source, path, content_hash, mtime, metadata, ingested_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (source, rel, digest, mtime, meta_json, _now()),
            ).lastrowid
            stats.added += 1
        conn.executemany(
            "INSERT INTO chunks (doc_id, seq, text, char_start, char_end) VALUES (?, ?, ?, ?, ?)",
            [(doc_id, c.seq, c.text, c.start, c.end) for c in chunks],
        )


def _walk_source(root: Path, include: list[str], exclude: list[str]):
    """Yield (rel_posix_path, abs_path) for files under root passing the globs.
    Excluded directories are pruned before descent (node_modules is never walked)."""
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = sorted(
            d for d in dirnames if not _dir_excluded(PurePosixPath(*(rel_dir / d).parts), exclude)
        )
        for f in sorted(filenames):
            rel = PurePosixPath(*(rel_dir / f).parts)
            if _matches(rel, include) and not _matches(rel, exclude):
                yield str(rel), Path(dirpath) / f


def _matches(rel: PurePosixPath, patterns: list[str]) -> bool:
    """Gitignore-style: patterns without a leading '/' match at any depth."""
    for pat in patterns:
        anchored = pat.startswith("/")
        pat = pat.lstrip("/")
        if rel.full_match(pat) or (not anchored and rel.full_match("**/" + pat)):
            return True
    return False


def _dir_excluded(rel: PurePosixPath, exclude: list[str]) -> bool:
    """A 'name/**' exclude prunes the directory 'name' itself, at any depth."""
    for pat in exclude:
        if not pat.endswith("/**"):
            continue
        base = pat[:-3]
        anchored = base.startswith("/")
        base = base.lstrip("/")
        if rel.full_match(base) or (not anchored and rel.full_match("**/" + base)):
            return True
    return False


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
