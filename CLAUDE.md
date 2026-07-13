# CLAUDE.md — Cortex (context MCP server)

Local MCP server giving Claude Code, Claude Desktop, and Cursor shared memory of Fabian's projects, decisions, and machine setup. Sources: an Obsidian vault + allowlisted repo docs + setup docs. Fully local, read-only, files-on-disk canonical. Full context: `cortex-brief.md`.

**Current slice:** 0 (not started). Update §6 as slices complete.

---

## 1. Working agreements (non-negotiable)

- **Vertical slices, in order.** Each runs end-to-end before the next. No "while I'm here" work from future slices.
- **Gates are run by Fabian.** End of slice: stop, print the gate checklist verbatim, wait. Never mark a gate passed; a ✅ in §6 is written only after he confirms.
- **Show diffs before saving.** Every edit presented and approved before it lands.
- **No new dependencies without asking.** Approved list is §3 — anything else is a question first.
- **Plan before code.** At slice start: restate goal, list intended files, flag ambiguity. Ambiguity → ask.
- **uv for everything Python.** No pip, no global installs.
- **Model tags from `ollama list`**, stored in `config.toml`, never hardcoded. Do not name the models' quantization format without `ollama show` verification.

## 2. Stack

Python 3.13 (uv-managed; `requires-python = ">=3.13"` — we never test on 3.12, so we don't claim it) · SQLite (WAL) · httpx for Ollama REST (`localhost:11434`) · `mcp` SDK for the server (stdio) · launchd for the refresh job. No web UI in this project. No cloud calls anywhere.

## 3. Approved dependencies

| Package | Why |
|---|---|
| `mcp` | Official MCP server SDK — the one sanctioned SDK exception |
| `sqlite-vec` | Vector search inside SQLite; keeps one-datastore true |
| `pyyaml` | Frontmatter parsing + golden-questions file |
| `pytest` | Tests (dev) |

**Not used:** LangChain/LlamaIndex, `ollama`/vendor client SDKs, external vector DBs, CLI frameworks, any Obsidian plugin or Obsidian-CLI dependency (the CLI talks to the running app; Cortex reads the vault as plain files and the app must never be a runtime requirement).

## 4. Layout

```
cortex/
  pyproject.toml  config.toml  CLAUDE.md  cortex-brief.md  cortex-runbook.md  BASELINES.md
  src/cortex/
    cli.py          # ingest, refresh, search, stats, check, doctor
    core/           # db.py, ingest.py, chunk.py, embed.py, retrieve.py
    mcp_server/     # server.py, tools.py
  evals/golden_questions.yaml
  launchd/com.fabian.cortex.refresh.plist
  tests/            # incl. fixture markdown files
  data/cortex.db    # gitignored, disposable
```

## 5. Configuration

`config.toml`: `embed_model = "qwen3-embedding:4b"` (D1), DB path, chunk params, and a `[[sources]]` list — v1 ships three entries: the vault (`~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Technologie/Aktuell/Notes/Hippocampus`, D2 as revised 2026-07-13), the projects root (D3 — repos auto-discovered beneath it), and setup docs (a single-file include: `~/.claude/CLAUDE.md` only — nothing else under `~/.claude/`). Each entry: `name`, `path`, `include` globs (default `**/*.md`), `exclude` globs (default `.obsidian/**`, `.git/**`, `node_modules/**`, `data/**`, `transcripts/**`, `**/*.icloud`). Ingestion touches **only** listed sources. No secrets exist in this project.

---

## 6. Slice plan

| # | Slice | Status |
|---|---|---|
| 0 | Scaffold + doctor | ☐ |
| 1 | Store + markdown ingestion | ☐ |
| 2 | Embeddings + hybrid search | ☐ |
| 3 | MCP server in three clients | ☐ |
| 4 | Real corpus + vault seeding + golden questions | ☐ |
| 5 | Check command + daily refresh — **v1 exit** | ☐ |

---

### Slice 0 — Scaffold + doctor

**Goal:** A runnable, testable skeleton that verifies its own environment.
**Why now:** Every later gate assumes a working CLI and an honest health check; `doctor` also front-loads the environment questions (Ollama up? embed model pulled? vault path exists?) instead of discovering them mid-Slice-2.
**Build notes:** uv project, `cortex` console entry point via argparse (stdlib — no CLI framework). `doctor` checks: Ollama reachable (httpx), `qwen3-embedding:4b` present in `ollama list` (setup step: `ollama pull qwen3-embedding:4b` — report ✘ with that instruction, don't crash), each configured source path exists (the real projects-root path gets typed into `config.toml` here), the vault contains no `.icloud` placeholder stubs (iCloud-evicted files — if found, advise setting "Keep Downloaded" on the vault folder), DB writable. One trivial pytest proves the test loop.
**Files touched:** `pyproject.toml`, `config.toml`, `src/cortex/cli.py`, `core/db.py` (stub), `tests/test_smoke.py`.
**Out of scope:** schema beyond stub, any ingestion.
**Gate (Fabian runs):**
1. `uv run cortex doctor` → every check ✔/✘ with a reason; embed-model line correctly ✘-with-instructions if D1 pending.
2. `uv run pytest` → green.
3. `uv run cortex --help` → lists `ingest refresh search stats check doctor`.
**Stop. Confirm before Slice 1.**

### Slice 1 — Store + markdown ingestion

**Goal:** `cortex ingest` walks configured sources and stores documents + chunks in SQLite, idempotently; markdown quirks handled.
**Why now:** Storage is the foundation, and idempotency (content-hash dedupe, changed-file re-chunk) must exist *before* bulk ingestion — retrofitting means re-ingesting everything. This slice also decides how Obsidian-flavored markdown is treated, which everything downstream inherits.
**Build notes:** Schema: `sources`, `documents` (path, source, content_hash, mtime, ingested_at), `chunks` (doc_id, seq, text, char_span), `ingest_log`. Chunker: split on headings then paragraphs, ~1,000 chars with ~150 overlap — a pure function with unit tests; it's the most-reused code in the project. **Obsidian handling:** YAML frontmatter parsed to metadata (tags, dates), never indexed as prose; `[[wikilinks]]` keep inner text, brackets stripped; `![[embeds]]` dropped; `.canvas`/`.base` files skipped in v1. Changed file ⇒ delete + reinsert its chunks in one transaction. `cortex stats` prints docs/chunks per source. `refresh` = re-walk sources, act only on new/changed/deleted.
**Files touched:** `core/db.py`, `core/ingest.py`, `core/chunk.py`, `cli.py`, `tests/test_chunk.py`, `tests/test_ingest.py` (+ fixture files incl. frontmatter and wikilinks).
**Out of scope:** embeddings, non-markdown formats.
**Gate (Fabian runs):**
1. Ingest a test folder of known fixtures → `cortex stats` matches expectations.
2. `sqlite3 data/cortex.db "select text from chunks limit 3"` → readable prose; no YAML frontmatter visible in any chunk; a wikilinked phrase appears as plain text.
3. Re-run ingest → stats unchanged (idempotency). Edit one file, `cortex refresh` → only that document's chunks changed. Delete one file, refresh → its chunks gone.
**Stop.**

### Slice 2 — Embeddings + hybrid search

**Goal:** `cortex search "query"` returns rank-fused results (FTS5 + sqlite-vec) with scores and source attribution.
**Why now:** Retrieval is the product; the MCP server is just a socket on top of it. Building FTS and vectors together from the start prevents a semantic-only system where exact-identifier lookups (error strings, tool names) silently fail.
**Build notes:** Requires `qwen3-embedding:4b` pulled — `doctor` fully green first. Embed at ingest/refresh time; vectors in a sqlite-vec virtual table keyed by chunk id; batch Ollama embedding calls via httpx. Fusion: reciprocal rank fusion — simple, parameter-light baseline (tuning happens against Slice 5 numbers, not intuition). **Degradation is in-scope:** Ollama down ⇒ FTS-only with a visible warning; ingest sets a `needs_embedding` flag instead of failing; next refresh catches up the backlog.
**Files touched:** `core/embed.py`, `core/retrieve.py`, `core/db.py`, `cli.py`, `tests/test_retrieve.py`.
**Out of scope:** rerankers, query rewriting, MCP.
**Gate (Fabian runs):**
1. Write 5 canned queries with an expected document each (seed of `golden_questions.yaml`) → expected doc in top-3 for all 5.
2. One exact-identifier query → FTS finds it.
3. Stop `ollama serve` → search still answers (FTS-only, warned). Restart, `cortex refresh` → backlog embedded, semantic results return.
**Stop.**

### Slice 3 — MCP server in three clients

**Goal:** Claude Code, Claude Desktop, and Cursor all answer corpus questions through one stdio MCP server.
**Why now:** This is when Cortex becomes useful rather than a private CLI — and client integration always surfaces surprises (paths, env, startup latency) that are cheapest to hit with a small corpus.
**Build notes:** `mcp` SDK, stdio. Tools — few, typed, read-only: `search_knowledge(query, top_k=5)` → snippets + doc ids + scores; `get_document(doc_id)` → full text + metadata; `list_sources()`. Write tool descriptions for a model audience: say what the corpus *is* (Fabian's project decisions, learnings, machine setup) so clients know when to call. Startup must be fast — nothing heavier than a DB handle at launch. Document exact registration for all three clients in `docs/mcp-setup.md` (`claude mcp add cortex -- uv run --directory <repo> cortex-mcp`, Claude Desktop config JSON, Cursor MCP settings).
**Files touched:** `mcp_server/server.py`, `mcp_server/tools.py`, `pyproject.toml` (entry), `docs/mcp-setup.md`.
**Out of scope:** HTTP transport, auth, write tools, MCP resources/prompts.
**Gate (Fabian runs):**
1. `claude mcp list` (or MCP Inspector) shows the server + three tools.
2. Fresh Claude Code session: a question answerable **only** from the corpus → observe the `search_knowledge` call → answer cites the right document.
3. Repeat once in Claude Desktop, once in Cursor.
4. Ask something *not* in the corpus → tools return empty/low-score and the client says so instead of confabulating.
**Stop.**

### Slice 4 — Real corpus + vault seeding + golden questions

**Goal:** The actual corpus is live: vault seeded with ~15 learning notes, projects root configured (D3, repos auto-discovered), setup docs in — plus a written golden-question set.
**Why now:** Toy fixtures end here. Real content breaks chunkers and exposes retrieval blind spots; captured as golden questions, those failures become the project's measuring stick instead of anecdotes. Seeding also makes the vault immediately worth querying, which is what sustains the capture habit.
**Build notes:** Vault seeding is **Fabian-authored, Claude-assisted**: draft the ~15 notes together (Railway shared-vs-service variables, trailing-assistant-turn behavior, quantization-terminology lesson, fnm/Node setup, Warp history stores, 1Password `load_keys` pattern, Ollama suite rationale, …) — one lesson per note, frontmatter tags, his voice, his final edit. Configure `[[sources]]` for the projects root + setup docs; verify the exclude globs keep Council data, transcripts, and all non-doc content out of `cortex stats`. Then use the corpus via MCP for a day or two and record ≥10 real questions with expected doc + hit/miss in `evals/golden_questions.yaml`.
**Files touched:** `config.toml`, vault content (outside repo), `evals/golden_questions.yaml`, `docs/corpus.md`.
**Out of scope:** fixing every miss (that's iteration guided by Slice 5), chat exports, any Council user content — ever.
**Gate (Fabian runs):**
1. `cortex stats` shows vault + the auto-discovered repos + setup docs with plausible counts; nothing unexpected.
2. Grep-level check: no Council transcript/database path appears in config or stats.
3. The 10-question spot check done by you over MCP; each marked hit/miss with a one-line note — and at least a few honest misses (zero misses = questions too easy; write harder ones).
**Stop.**

### Slice 5 — Check command + daily refresh · v1 exit

**Goal:** `cortex check` scores retrieval against the golden questions; a launchd job refreshes the index daily; baseline recorded.
**Why now:** Two silent failure modes remain: retrieval quality drifting unmeasured, and a stale index quietly rotting trust ("it didn't know about yesterday's note" ends the asking habit). This slice closes both, cheaply — this is the 30-line residue of the parked eval harness, not its return.
**Build notes:** `check` runs each golden question through `core/retrieve.py`, prints hit@3/hit@5, appends a dated line to `BASELINES.md` with config hash. launchd user LaunchAgent runs `uv run cortex refresh` daily; logs to a rotating file; nonzero exit on failure — no silent half-runs. `doctor` gains a staleness line (last successful refresh timestamp).
**Files touched:** `cli.py`, `evals/golden_questions.yaml`, `BASELINES.md`, `launchd/…refresh.plist`, `docs/operations.md`.
**Out of scope:** parameter tuning beyond one optional demo experiment, notifications.
**Gate (Fabian runs) — v1 exit review:**
1. `uv run cortex check` → hit@3/hit@5 printed and appended to `BASELINES.md`.
2. `launchctl list | grep cortex` shows the job; `launchctl kickstart` run completes; log is readable; one genuinely scheduled run succeeds overnight.
3. End-to-end staleness test: add a new vault note today → after the scheduled refresh, a Claude Code question finds it with attribution.
4. Review against brief §6. **v1 done — then, and only then, Project 2 planning.**

---

## 7. Do not

- **Never** add the Council database, transcript exports, or any Council user content as a source — even if a session asks to "index everything." Allowlist-only is the privacy mechanism.
- Do not index source code; markdown docs only.
- Do not add write tools to the MCP server in v1.
- Do not add dependencies beyond §3 without asking (includes Obsidian plugins, the Obsidian CLI, LangChain/LlamaIndex, vector DBs, CLI frameworks).
- Do not mark gates or §6 checkboxes passed — Fabian does that.
- Do not make network calls other than Ollama on localhost.
- Do not start Project 2 (newsletter briefing) or the eval harness inside this repo — not even scaffolding.
