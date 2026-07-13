# Cortex — Project Brief (v2, descoped)

**One-liner:** A local MCP server that gives Claude Code, Claude Desktop, and Cursor shared memory of your projects, decisions, and machine setup — fed by an Obsidian vault and your repos' docs.

**What changed from v1 of this brief:** The Monday newsletter briefing is now **Project 2**, built separately after this ships. The eval harness is **parked** (it returns if/when a real model decision looms). What remains is one product with one job: your AI tools stop starting from zero.

---

## 1. The job

Any Claude Code, Claude Desktop, or Cursor session can ask things like "what was the Railway shared-variables gotcha?", "how is `load_keys` set up?", "what did the Council brief decide about turn structure?" — and get an answer with the source document, via one MCP server searching your personal corpus. You never interact with Cortex directly; it's plumbing.

## 2. The corpus

**In (v1):**
1. **Obsidian vault** *(new — your decision)*: the capture surface for decisions, learnings, and gotchas going forward. Seeded during Slice 4 with ~15 notes porting the known lessons (Railway variables, trailing-assistant-turn behavior, quantization terminology, fnm/Node setup, Warp history stores, …).
2. **Repo docs** from your projects root (path set at Slice 0): every repo beneath it is auto-discovered — `README`s, `CLAUDE.md`s, briefs, `docs/` — markdown only, never source code. New repos join the corpus automatically.
3. **Mac & tooling setup docs** — concretely a single file for now: `~/.claude/CLAUDE.md` (an include for that file only; nothing else under `~/.claude/` ever enters the corpus, since it's full of machine-generated markdown). The rest of the setup knowledge — model-suite rationale, environment notes — arrives as vault Learnings notes via Slice 4's seeding.

**Deferred:** curated claude.ai chat exports (noisy; revisit once the vault habit works).

**Never:**
- **Council user content** — pitches, discussions, transcripts. Excluded *structurally*: ingestion is allowlist-only, and the Council database is simply never a source. The Council **repo's engineering docs** are in via source 2; the tool's personal content is not, ever.
- **Source code** — Claude Code reads code agentically already; this server is for cross-project knowledge that isn't in the repo currently open.
- **Newsletters** — Project 2's territory.

## 3. Division of labor with Obsidian

The vault (plus repo docs) on disk is **canonical**; SQLite holds only the **derived index** (chunks, FTS, vectors) and can be deleted and rebuilt at any time. Cortex reads the vault as plain markdown files directly from disk — no Obsidian plugins, no Local REST API, no community Obsidian MCP server needed. Obsidian is where *you* read, write, and link; Cortex is how *machines* find it. If Obsidian ever exits your life, the vault is still a folder of markdown and nothing breaks.

## 4. Architecture decisions

- **A1 — Files are canonical, SQLite is disposable index.** Hash-based idempotent re-ingest; `cortex refresh` (and a daily launchd job) picks up edits.
- **A2 — SQLite only**: FTS5 + `sqlite-vec` in one file. Hybrid retrieval (keyword + semantic, rank-fused) — owned code, no LangChain/LlamaIndex; owning retrieval is half the learning goal.
- **A3 — Embeddings via Ollama**, graceful degradation to FTS-only when Ollama is down; embedding backlog caught up on next refresh.
- **A4 — httpx, not SDKs.** One sanctioned exception: the official `mcp` package for the server (hand-rolling JSON-RPC/stdio is plumbing without learning value).
- **A5 — Read-only MCP server**, three tools: `search_knowledge`, `get_document`, `list_sources`. No write tools in v1.
- **A6 — Gates run by Fabian**, never self-graded.
- **A7 — Fully local.** v1 makes zero cloud calls; no Anthropic key required anywhere.

## 5. Decisions (resolved)

- **D1 — Embedding model: `qwen3-embedding:4b`.** Still the quality leader among Ollama-pullable embedders as of mid-2026 — multilingual (relevant for mixed DE/EN notes), flexible output dimensions — and it's the known quantity from the previous suite. At ~3–4 GB it loads only during ingest/refresh, trivial next to the chat models. Tiny fallback if disk ever matters: `embeddinggemma` (~600 MB).
- **D2 — Vault: `Hippocampus`, in iCloud Drive** (`~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Technologie/Aktuell/Notes/Hippocampus`). *Revised 2026-07-13:* originally placed in Obsidian's iCloud container because that's the only iCloud location the iPhone app can open as a vault; the vault was created in iCloud Drive instead and iPhone-app access was dropped as a requirement. Mobile capture stays out until/unless the vault moves to the Obsidian container or Obsidian Sync. Still iCloud-synced, so: Mac folder set to "Keep Downloaded"; ingestion skips `.icloud` placeholder stubs and `doctor` warns if any appear. Free; the upgrade path is Obsidian Sync (paid) — in which case the vault must leave iCloud first (never double-sync).
- **D3 — Whole projects root allowlisted** (actual path typed into config at Slice 0). Repos beneath it are auto-discovered — new projects join the corpus automatically. Safety comes from the glob rules: markdown only, with `data/**`, `transcripts/**`, `.git/**`, `node_modules/**`, `.obsidian/**` excluded — plus the standing rule that Council user content is never a source.

## 6. Success criteria (v1 done)

1. A question answerable only from the corpus is answered — with correct source attribution — inside Claude Code, Claude Desktop, **and** Cursor, via the same server.
2. `cortex check` (golden-question smoke test) reports hit@3/hit@5, recorded once as baseline.
3. The vault is alive: ≥15 seeded notes and new ones appearing without ceremony.
4. Everything works offline; Ollama down degrades gracefully instead of breaking.
5. Index refresh runs unattended daily; a note added today is findable tomorrow without manual steps.

## 7. Roadmap (not in v1)

- **P2 — Monday briefing**: separate project, separate brief, after this ships. Whether its archive ever feeds Cortex stays an open question until then.
- **P3 — Eval harness**: revived when a model release forces a real adopt/skip decision.

## 8. Risks, honestly

- **The capture habit is the real dependency.** Cortex makes notes retrievable everywhere, which is the payoff that sustains the habit — but the tool cannot create the habit. If the vault stalls at 15 seeded notes, v1 still serves repo docs, but the ceiling drops.
- **Retrieval will plateau.** Hybrid search is good, not magic; the golden-question file is the honest measuring stick, not anecdotes.
- **Stale index rots trust silently** — one "it didn't know about yesterday's note" and you stop asking. The daily refresh job plus `cortex doctor` staleness check exist for exactly this.
