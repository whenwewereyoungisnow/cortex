# Cortex

A local MCP server that gives Claude Code, Claude Desktop, and Cursor shared
memory of my projects, decisions, and machine setup — so my AI tools stop
starting from zero.

Ask any session "what was the Railway shared-variables gotcha?" or "how is
`load_keys` set up?" and get an answer with the source document. I never
interact with Cortex directly; it's plumbing.

## How it works

```
Obsidian vault ─┐
repo docs      ─┼─→ cortex ingest ─→ SQLite (FTS5 + sqlite-vec) ─→ MCP server (stdio)
setup docs     ─┘        ↑                                              ↓
                  daily launchd refresh              Claude Code · Claude Desktop · Cursor
```

- **Files are canonical, SQLite is a disposable index.** The Obsidian vault
  and repo markdown on disk are the source of truth; the database can be
  deleted and rebuilt at any time.
- **Hybrid retrieval, owned code.** FTS5 keyword search + `sqlite-vec`
  semantic search, rank-fused. No LangChain/LlamaIndex — owning retrieval is
  half the learning goal.
- **Embeddings via Ollama** (`qwen3-embedding:4b`), fully local. Ollama down
  degrades gracefully to keyword-only search.
- **Read-only MCP server** with three tools: `search_knowledge`,
  `get_document`, `list_sources`.
- **Allowlist-only ingestion** — only the sources listed in `config.toml` are
  ever touched, markdown only, never source code.
- **Zero cloud calls.** Everything runs on this machine.

## Status

Built in vertical slices, each gated by a manual review before the next
starts.

| # | Slice | Status |
|---|---|---|
| 0 | Scaffold + doctor — CLI skeleton, environment health check | ✅ 2026-07-13 |
| 1 | Store + markdown ingestion — idempotent SQLite ingest, Obsidian-aware chunking | up next |
| 2 | Embeddings + hybrid search — FTS5 + vectors, rank fusion, graceful degradation | planned |
| 3 | MCP server in three clients — stdio server, registration docs | planned |
| 4 | Real corpus — vault seeding (~15 notes), golden questions | planned |
| 5 | Check command + daily launchd refresh — **v1 exit** | planned |

**v1 is done when:** corpus questions are answered with correct source
attribution in all three clients; `cortex check` reports hit@3/hit@5 against
a golden-question set; the index refreshes daily unattended; and everything
keeps working offline.

**Not in v1:** the Monday newsletter briefing (Project 2, separate repo) and
the eval harness (parked until a real model decision looms).

## Usage

```sh
uv sync                    # install (Python 3.13, uv-managed)
uv run cortex doctor       # verify environment: config, Ollama, sources, database
uv run pytest              # tests
uv run cortex --help       # all commands: ingest refresh search stats check doctor
```

Commands run from the repo root (`config.toml` is resolved relative to the
working directory — see `docs/operations.md`).

## Configuration

`config.toml` holds the embedding model tag (from `ollama list`, never
hardcoded), the database path, chunking parameters, and the source allowlist:
the Obsidian vault, a projects root (repos beneath it auto-discovered,
markdown only), and a single-file include for the global Claude setup doc.

## Stack

Python 3.13 · SQLite (WAL, FTS5, `sqlite-vec`) · `httpx` for Ollama's REST
API · the official `mcp` SDK for the server · `launchd` for the daily
refresh. Dependencies are deliberately few; see `CLAUDE.md` §3 for the
approved list.

Full context: [`cortex-brief.md`](cortex-brief.md) (the why),
[`CLAUDE.md`](CLAUDE.md) (working agreements + slice plan),
[`cortex-runbook.md`](cortex-runbook.md) (operations).
