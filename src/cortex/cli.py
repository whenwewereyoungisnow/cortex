"""Cortex CLI: ingest, refresh, search, stats, check, doctor."""

import argparse
import sqlite3
import sys
import tomllib
from pathlib import Path
from typing import Any

import httpx

from cortex.core import db, ingest

CONFIG_NAME = "config.toml"
REQUIRED_KEYS = ("embed_model", "ollama_url", "db_path", "sources")

# Commands that exist as stubs until their slice lands.
ARRIVES_IN_SLICE = {"search": 2, "check": 5}


class ConfigError(Exception):
    pass


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise ConfigError(f"{config_path} not found — run from the repo root")
    try:
        with config_path.open("rb") as f:
            cfg = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{config_path} is not valid TOML: {e}") from e
    for key in REQUIRED_KEYS:
        if key not in cfg:
            raise ConfigError(f"{config_path}: missing required key '{key}'")

    base = config_path.resolve().parent
    db_path = Path(cfg["db_path"]).expanduser()
    cfg["db_path"] = db_path if db_path.is_absolute() else base / db_path
    for source in cfg["sources"]:
        source["path"] = Path(source["path"]).expanduser()
    return cfg


def fetch_ollama_models(url: str) -> list[str] | None:
    """Model tags known to Ollama, or None if it isn't reachable."""
    try:
        resp = httpx.get(f"{url}/api/tags", timeout=2.0)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    return [m["name"] for m in resp.json().get("models", [])]


def cmd_doctor(args: argparse.Namespace) -> int:
    failures = 0

    def report(ok: bool, label: str, detail: str) -> None:
        nonlocal failures
        if not ok:
            failures += 1
        print(f"  {'✔' if ok else '✘'} {label}: {detail}")

    try:
        cfg = load_config(Path(CONFIG_NAME))
    except ConfigError as e:
        report(False, "config", str(e))
        return 1
    report(True, "config", f"{CONFIG_NAME} loaded ({len(cfg['sources'])} sources)")

    models = fetch_ollama_models(cfg["ollama_url"])
    if models is None:
        report(False, "ollama", f"not reachable at {cfg['ollama_url']} — start the Ollama app (or `ollama serve`)")
        report(False, "embed model", f"cannot check for {cfg['embed_model']} while Ollama is down")
    elif cfg["embed_model"] in models:
        report(True, "ollama", f"reachable at {cfg['ollama_url']} ({len(models)} models)")
        report(True, "embed model", f"{cfg['embed_model']} present")
    else:
        report(True, "ollama", f"reachable at {cfg['ollama_url']} ({len(models)} models)")
        report(False, "embed model", f"{cfg['embed_model']} not pulled — run: ollama pull {cfg['embed_model']}")

    for source in cfg["sources"]:
        name, path = source["name"], source["path"]
        if not path.exists():
            report(False, f"source {name}", f"{path} does not exist")
            continue
        report(True, f"source {name}", str(path))
        # .icloud stubs are eviction placeholders; they only occur inside iCloud containers.
        if path.is_dir() and "Library/Mobile Documents" in str(path):
            stubs = list(path.rglob("*.icloud"))
            if stubs:
                report(
                    False,
                    f"{name} .icloud stubs",
                    f"{len(stubs)} found — files are iCloud-evicted; set 'Keep Downloaded' on the folder",
                )
            else:
                report(True, f"{name} .icloud stubs", "none")

    try:
        conn = db.connect(cfg["db_path"])
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        report(True, "database", f"{cfg['db_path']} writable (journal_mode={mode})")
    except (OSError, sqlite3.Error) as e:
        report(False, "database", f"{cfg['db_path']} not writable: {e}")

    print(f"\n{failures} check(s) failed" if failures else "\nall checks passed")
    return 1 if failures else 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Shared by `ingest` and `refresh`: both walk every source and act only
    on new/changed/deleted files (refresh grows extra duties in Slice 2)."""
    cfg = _load_config_or_report()
    if cfg is None:
        return 1
    conn = db.connect(cfg["db_path"])
    try:
        results = ingest.sync(conn, cfg)
    finally:
        conn.close()
    missing = False
    for name, s in results.items():
        line = f"  {name}: {s.added} added, {s.changed} changed, {s.deleted} deleted, {s.skipped} skipped"
        if s.missing:
            line += " — SOURCE PATH MISSING"
            missing = True
        print(line)
    return 1 if missing else 0


def cmd_stats(args: argparse.Namespace) -> int:
    cfg = _load_config_or_report()
    if cfg is None:
        return 1
    conn = db.connect(cfg["db_path"])
    try:
        rows = ingest.corpus_stats(conn)
    finally:
        conn.close()
    if not rows:
        print("index is empty — run: cortex ingest")
        return 0
    for source, docs, chunks in rows:
        print(f"  {source}: {docs} docs, {chunks} chunks")
    return 0


def _load_config_or_report() -> dict[str, Any] | None:
    try:
        return load_config(Path(CONFIG_NAME))
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return None


def cmd_stub(args: argparse.Namespace) -> int:
    print(
        f"cortex {args.command} is not built yet — arrives in Slice {ARRIVES_IN_SLICE[args.command]}",
        file=sys.stderr,
    )
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cortex",
        description="Local knowledge index: ingest markdown sources, search them, serve via MCP.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest", help="walk configured sources and (re)index documents")
    sub.add_parser("refresh", help="re-walk sources; act only on new/changed/deleted files")
    p_search = sub.add_parser("search", help="hybrid keyword+semantic search over the corpus")
    p_search.add_argument("query", help="search query")
    sub.add_parser("stats", help="print docs/chunks per source")
    sub.add_parser("check", help="score retrieval against the golden questions")
    sub.add_parser("doctor", help="verify environment: config, Ollama, sources, database")
    return parser


COMMANDS = {
    "doctor": cmd_doctor,
    "ingest": cmd_sync,
    "refresh": cmd_sync,
    "stats": cmd_stats,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS.get(args.command, cmd_stub)(args)


if __name__ == "__main__":
    sys.exit(main())
