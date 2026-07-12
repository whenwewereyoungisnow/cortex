# Cortex — Operator Runbook

This is **your** document — what you type and say, in order. The brief explains *why*, CLAUDE.md tells *Claude Code* what to build; this file drives the sessions. One assumption throughout: your projects folder is `~/Developer` — **if it lives elsewhere, substitute your path in every command below.**

---

## Phase A — One-time prep (before any code, ~20 min)

**Step 1 — Pull the embedding model.**
```bash
ollama pull qwen3-embedding:4b
ollama list        # confirm it appears alongside qwen3.6 and gemma4
```

**Step 2 — Vault quick pre-flight.** The full Day-7 check is in the week-1 enablement plan; the minimum before Cortex starts:
```bash
find "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Hippocampus" -name "*.icloud"
```
Expected output: **nothing**. If placeholder files appear, right-click the Hippocampus folder in Finder → *Keep Downloaded*, wait for iCloud to finish, re-run.

**Step 3 — Create the project folder and repo.** (Never inside iCloud.)
```bash
mkdir -p ~/Developer/cortex && cd ~/Developer/cortex
git init -b main
```

**Step 4 — Move the three docs in and commit.** Download `cortex-brief.md`, `CLAUDE.md`, and this runbook from our chat, then:
```bash
mv ~/Downloads/cortex-brief.md ~/Downloads/CLAUDE.md ~/Downloads/cortex-runbook.md ~/Developer/cortex/
ls    # verify: CLAUDE.md is spelled exactly like that, uppercase
git add -A && git commit -m "docs: brief, CLAUDE.md, runbook"
```

**Step 5 — Start the first session.**
```bash
cd ~/Developer/cortex && claude
```

---

## Phase B — Slice 0, fully walked through (this sets the pattern)

**Step 6 — Paste this prompt:**

> Read CLAUDE.md and cortex-brief.md in full. We're starting **Slice 0 (scaffold + doctor)**. Per the working agreements: restate the slice goal, list the files you intend to create, and flag anything ambiguous — then wait for my approval before writing anything. The projects root for config.toml is `~/Developer`.

**Step 7 — Approve the plan, then review diffs.** Claude Code should show every file before saving. If it starts writing without showing a plan first, say: *"Stop — working agreements. Plan first, then diffs."*

**Step 8 — It stops and prints the gate checklist. Now you run the gate yourself** (second terminal, or after exiting):
```bash
uv run cortex doctor    # every line ✔/✘ with a reason; embed-model line ✔ since Step 1
uv run pytest           # green
uv run cortex --help    # lists: ingest refresh search stats check doctor
```

**Step 9 — Close the slice.**
```bash
git add -A && git commit -m "slice 0: scaffold + doctor"
```
Tell Claude Code: *"Gate passed — tick Slice 0 in §6."* (Only you ever say this.)

**The rhythm, from here on:** one slice per session → paste the slice prompt → approve plan → review diffs → **you** run the gate → commit → tick the box. If a gate fails, paste the exact output back into the session, let it fix, re-run the gate. Never proceed past a failed gate; never let a session "pre-work" the next slice.

---

## Phase C — Slices 1–5

### Slice 1 — Store + markdown ingestion

**Prompt:**
> Read CLAUDE.md. Slice 0 is done. We're starting **Slice 1 (store + markdown ingestion)**. Plan first, wait for approval.

**Your gate:**
```bash
uv run cortex ingest tests/fixtures      # or the test folder it created
uv run cortex stats                      # counts match the fixtures
sqlite3 data/cortex.db "select text from chunks limit 3;"   # readable prose, no YAML, no [[brackets]]
uv run cortex ingest tests/fixtures      # re-run → stats unchanged
```
Then edit one fixture file, `uv run cortex refresh`, confirm only that document changed. Delete one, refresh, confirm its chunks are gone.
Commit: `git commit -am "slice 1: store + ingestion"` → tick the box.

### Slice 2 — Embeddings + hybrid search

**Prompt:**
> Read CLAUDE.md. We're starting **Slice 2 (embeddings + hybrid search)**. Plan first, wait for approval.

**Your gate:**
```bash
uv run cortex search "your five canned queries, one at a time"   # expected doc in top-3, all five
uv run cortex search "some-exact-identifier"                      # keyword path finds it
```
Fallback test: quit the Ollama app → `uv run cortex search "..."` still answers (FTS-only, visible warning) → restart Ollama → `uv run cortex refresh` catches up the embedding backlog.
Commit: `"slice 2: hybrid search"` → tick.

### Slice 3 — MCP server in three clients

**Prompt:**
> Read CLAUDE.md. We're starting **Slice 3 (MCP server)**. Plan first. Also produce docs/mcp-setup.md with exact registration steps for Claude Code, Claude Desktop, and Cursor.

**Your gate — registration is your job, per client, following docs/mcp-setup.md:**
1. Claude Code: `claude mcp add cortex -- uv run --directory ~/Developer/cortex cortex-mcp`, then `claude mcp list`.
2. Claude Desktop: add the JSON block to `~/Library/Application Support/Claude/claude_desktop_config.json`, restart the app.
3. Cursor: MCP settings, same command.

Then in a **fresh** session of each client, ask one question answerable only from the fixture corpus — watch for the `search_knowledge` call and a correct citation. Ask one question that's *not* in the corpus — the client should say so, not invent. 
Commit: `"slice 3: mcp server + client registration"` → tick.

### Slice 4 — Real corpus + vault seeding + golden questions (the human slice)

This one is mostly **your** work, spread over 2–3 days.

**Step 4a — Seed ~15 Learnings notes into Hippocampus.** One topic per note, filename = title, frontmatter per the vault contract. Draft them with me or with Claude Code, but final wording is yours. The list, all real lessons you already own:
1. Railway shared vs. service variables (explicit opt-in per service)
2. Chat-tuned models & trailing assistant turns (inline prior contributions instead)
3. NVFP4 on Apple Silicon — encoding vs. Blackwell acceleration (the resolved version)
4. Homebrew `mlx`/`mlx-c` are load-bearing for Ollama's MLX backend
5. uv updates via `brew upgrade uv`, never `uv self update`
6. Node via fnm only
7. Python via uv only (no pip, no conda)
8. `load_keys` / 1Password CLI credential pattern
9. GitHub no-reply commit email (GH007 fix)
10. Warp's two history stores
11. Obsidian vault must live in the iCloud~md~obsidian container; Keep Downloaded; `.icloud` stubs
12. External renames don't update wikilinks (create/append, never rename)
13. Council branch strategy → provider-abstraction lesson
14. gemma4:31b MTP draft head needs Ollama ≥ 0.31
15. Obsidian CLI = remote control for the running app, never a headless dependency

**Step 4b — Session prompt:**
> Read CLAUDE.md. We're starting **Slice 4 (real corpus)**. Configure the sources: vault at the Hippocampus path, projects root `~/Developer`, setup docs = the single file `~/.claude/CLAUDE.md`. Plan first.

**Step 4c — Your gate:** `uv run cortex stats` shows vault + auto-discovered repos + setup docs, nothing unexpected. Grep-check that no Council data path appears in `config.toml`. Then **use it for a day or two** — ask real questions through Claude Code — and log ≥10 of them with hit/miss into `evals/golden_questions.yaml`. At least a few honest misses; zero misses means the questions are too easy.
Commit: `"slice 4: real corpus + golden questions"` → tick.

### Slice 5 — Check command + daily refresh (v1 exit)

**Prompt:**
> Read CLAUDE.md. We're starting **Slice 5 (check + launchd refresh)** — the v1 exit slice. Plan first.

**Your gate:**
```bash
uv run cortex check                                        # hit@3 / hit@5 printed, appended to BASELINES.md
launchctl list | grep cortex                               # job is loaded
launchctl kickstart -k gui/$(id -u)/com.fabian.cortex.refresh   # manual run completes; read the log
```
Overnight test: add one new note to the vault today → tomorrow, ask a Claude Code question about it → it's found, with attribution.
Commit: `"slice 5: check + scheduled refresh"` → tick.

---

## Phase D — v1 exit review (10 minutes, against brief §6)

Walk the five success criteria in the brief; each one is observable, none is Claude's word for it. All five hold → **v1 done. Only now does Montag planning start.**

---

## When things go sideways

- **Gate fails** → paste the full error into the session; fix; re-run the *whole* gate, not just the failed line.
- **Session gets long/confused** → end it. Start fresh with "Read CLAUDE.md, we're mid Slice N, here's where it stands." CLAUDE.md + git are the memory; sessions are disposable.
- **Claude Code wants a new dependency** → §3 is the list. If it's not on it, the answer is a question to you, not an install.
- **It claims a gate passed** → it can't. Gates pass when you say so.
