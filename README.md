```
 ██████╗ ██████╗ ███████╗██╗██████╗ ██╗ █████╗ ███╗   ██╗
██╔═══██╗██╔══██╗██╔════╝██║██╔══██╗██║██╔══██╗████╗  ██║
██║   ██║██████╔╝███████╗██║██║  ██║██║███████║██╔██╗ ██║
██║   ██║██╔══██╗╚════██║██║██║  ██║██║██╔══██║██║╚██╗██║
╚██████╔╝██████╔╝███████║██║██████╔╝██║██║  ██║██║ ╚████║
 ╚═════╝ ╚═════╝ ╚══════╝╚═╝╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝
        ██╗     ███████╗ ██████╗ ██╗ ██████╗ ███╗   ██╗
        ██║     ██╔════╝██╔════╝ ██║██╔═══██╗████╗  ██║
        ██║     █████╗  ██║  ███╗██║██║   ██║██╔██╗ ██║
        ██║     ██╔══╝  ██║   ██║██║██║   ██║██║╚██╗██║
        ███████╗███████╗╚██████╔╝██║╚██████╔╝██║ ╚████║
        ╚══════╝╚══════╝ ╚═════╝ ╚═╝ ╚═════╝ ╚═╝  ╚═══╝
 One contract. Every agent. Zero sludge.
```

# Obsidian Legion

> **One task contract. Every agent. No coordination sludge.**

<img src="./tui-intro.gif" alt="Obsidian Legion Terminal Intro" />

<details>
<summary>See the wiki compile in action</summary>

<img src="./demo.gif" alt="Obsidian Legion Wiki Compile Demo" />

</details>

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-green.svg)](https://www.python.org/)
![Version](https://img.shields.io/badge/version-0.3.0-blue)
![Tests](https://img.shields.io/badge/tests-18%2F18-brightgreen)
![Pattern](https://img.shields.io/badge/pattern-Karpathy%20LLM%20Wiki-orange)
![Layers](https://img.shields.io/badge/memory-5--layer%20architecture-purple)

## 10-Second Summary

**What**: Multi-agent task engine + LLM Wiki compiler. Markdown files ARE the database.
**Why**: 4 AI agents + 1 vault = 3 conflicting to-do lists. Unless they share one contract. And an LLM that compiles your vault into a navigable wiki.
**Install**: Give [`INSTALL_ME.md`](INSTALL_ME.md) to your LLM and let it set you up.
**Agents**: Claude, Codex, Gemini, Ollama -- same verbs, same files, zero sludge.

## What's New in v0.3.0

| Feature | v0.2.0 | v0.3.0 |
|---------|--------|--------|
| **Task engine** | Shared Markdown tasks | Shared Markdown tasks |
| **Multi-agent coordination** | CLI + MCP | CLI + MCP |
| **LLM Wiki compiler** | Karpathy pattern: compile, don't retrieve | Karpathy pattern: compile, don't retrieve |
| **5-layer memory** | 3-layer (CLI / Wiki / Qdrant) | 5-layer (Graphify / CLI / Wiki / Qdrant / MCP) |
| **Graphify integration** | -- | Layer 0: knowledge graph from code/docs/media |
| **Vault-wide scan** | `--vault-wide` compiles entire vault | `--vault-wide` compiles entire vault |
| **Model tiers** | Heavy (cloud) / Light (local) | Heavy (cloud) / Light (local) |
| **Deep search** | `--deep` falls back to Qdrant vectors | `--deep` falls back to Qdrant vectors |
| **MCP tools** | 8 tools | 10 tools (+ graphify_build, graphify_query) |
| **Tests** | 18 | 22 |

## Architecture: 5-Layer Memory

```
                    Query arrives
                         |
              Layer 0: Graphify (optional)
              (knowledge graph from code, docs, media)
              71.5x fewer tokens. AST + semantic.
              pip install graphifyy
                         |
                    Layer 1: Obsidian CLI + Legion
                    (direct vault read, task coordination)
                    Fastest. Free. No model needed.
                         |
                    Layer 2: LLM Wiki (Karpathy pattern)
                    (compiled articles, wikilinks, searchable index)
                    The LLM read it once and WROTE the wiki.
                         |
                    Layer 3: Qdrant Vector Search
                    (semantic similarity across entire vault)
                         |
                    Layer 4: MCP Server
                    (Claude Code, Codex, Gemini, Ollama talk to it)
```

The key insight from [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):
traditional RAG is stateless -- it re-discovers knowledge every query.
The wiki compiler does the heavy work **once** and produces persistent,
navigable knowledge that lives in your vault as plain Markdown.

---

Obsidian Legion is a vault-native task engine for multi-agent Obsidian vaults.
It is designed around one hard rule: **the source of truth is plain Markdown
inside the vault**, not a plugin database, not an external API, not a JSON blob
hidden in some config directory. If you can read the vault, you can read the
task state.

## Why This Exists

Modern vaults attract multiple builders. You might have Codex writing Python,
Claude Code wiring infrastructure, Gemini CLI doing research, and a local
Ollama agent handling small jobs -- all in the same repository. That is power.
It is also a coordination nightmare.

The failure mode is predictable: Agent A creates a task in its own format.
Agent B cannot read it and creates a duplicate. The human opens Obsidian and
sees three conflicting to-do lists. Coordination sludge wins.

Obsidian Legion fixes this by giving **every agent the same verbs** against
**the same vault data**. Tasks are canonical Markdown with YAML frontmatter.
Agents interact through a shared CLI (or MCP surface). Dashboards are
regenerated Markdown that Obsidian renders natively. No plugins required. No
app needs to be running. Just files.

## Architecture

### Project

```
obsidian-legion/
├── bin/obsidian-legion{,-mcp}   # Shell wrappers (no install needed)
├── docs/INTEGRATIONS.md         # Per-agent rollout contracts
├── scripts/setup-{claude,gemini}-mcp.sh
├── src/obsidian_legion/
│   ├── cli.py          config.py      mcp_server.py
│   ├── models.py       store.py
├── tests/
└── pyproject.toml
```

### Vault (created by `bootstrap`)

```
<VAULT_ROOT>/06-daily/action-points/
├── tasks/YYYY/MM/               # Canonical task notes
├── dashboards/                  # Auto-generated Obsidian dashboards
├── daily/YYYY/                  # Human-readable daily rollups
├── reviews/                     # Weekly review snapshots
└── config/agents.yaml           # Registered agent labels
```

The official Obsidian CLI is treated as an optional accelerator, not a
dependency. Legion works whether the Obsidian app is running or not.

## Task Contract

Each task is a Markdown file with YAML frontmatter:

```yaml
---
task_id: TASK-20260407-001
title: Roll out Obsidian Legion adoption
summary: Create the shared task contract and first workflow docs.
status: in_progress       # inbox | ready | in_progress | waiting | blocked | done | cancelled
priority: P1              # P0 | P1 | P2 | P3
assignee: codex           # human | codex | claude-code | gemini-cli | ollama | ...
project: obsidian-legion
area: vexnet
lane: this-week           # today | this-week | backlog | someday
effort: m                 # s | m | l | xl
created_at: "2026-04-07T18:45:00+02:00"
updated_at: "2026-04-07T19:12:00+02:00"
due: null
tags: []
blockers: []
acceptance:
  - CLI works against canonical Markdown tasks.
  - Dashboards render into the vault.
log:
  - "2026-04-07T18:45:00+02:00 - Created by human"
  - "2026-04-07T19:12:00+02:00 - Claimed by codex"
---
```

The body below the frontmatter is free-form Markdown; the engine only reads the
frontmatter.

## CLI Reference

All commands accept `--vault-root <path>`. If omitted, the engine walks up from
the current directory looking for the vault.

| Verb | Description |
|------|-------------|
| `bootstrap` | Create the required directory tree and config files. Safe to run repeatedly. |
| `capture` | Create a new task note. Accepts `--summary`, `--priority`, `--assignee`, `--project`, `--area`, `--lane`, `--effort`, `--due`, `--accept` (repeatable), and more. |
| `list` | Query tasks by `--status`, `--assignee`, `--project`. Output as `--format table\|json\|ids`. |
| `next` | Show highest-priority actionable tasks for a given `--assignee`. Default limit: 10. |
| `claim` | Assign yourself (or an agent) to a task and move it to `in_progress`. |
| `update` | Patch any field: status, priority, assignee, lane, tags, blockers, and `--log-note` for history. |
| `done` | Mark a task completed. Optionally add a `--note`. |
| `refresh` | Rebuild all dashboards and rollups from canonical task data. |
| `doctor` | Run health checks for vault structure, optional dependencies, and MCP readiness. Defaults to a human report; add `--format json` for automation. |

Most mutating verbs accept `--refresh` to regenerate dashboards automatically.

## Agent Lifecycle

Every agent -- human or machine -- follows the same loop:

```
  next ──> claim ──> work ──┬──> done ──> refresh
                            │
                            └──> update (blocked/waiting) ──> refresh
```

In practice:

```bash
obsidian-legion next --assignee codex
obsidian-legion claim TASK-20260407-001 --assignee codex
# ... do the work ...
obsidian-legion done TASK-20260407-001 --refresh
```

If blocked:

```bash
obsidian-legion update TASK-20260407-001 \
  --status blocked --log-note "Waiting on API key." --refresh
```

## Installation

### Option 1: Give This Repo to Your LLM (Recommended)

Clone the repo, then hand [`INSTALL_ME.md`](INSTALL_ME.md) to Claude Code, Codex,
Gemini CLI, or any coding LLM. It contains step-by-step instructions the LLM
can follow to set everything up for your specific environment.

```bash
git clone https://github.com/valx-vex/obsidian-legion.git
cd obsidian-legion
# Now open your LLM and say: "Read INSTALL_ME.md and set this up for my vault at ~/my-vault"
```

### Option 2: Installer Script

```bash
git clone https://github.com/valx-vex/obsidian-legion.git
cd obsidian-legion
bash install.sh
```

Checks prerequisites (Python 3.11+, Ollama), creates a virtual environment,
installs dependencies, and pulls the default model.

### Option 3: Manual

```bash
git clone https://github.com/valx-vex/obsidian-legion.git
cd obsidian-legion
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
ollama pull llama3.2:3b
```

If you only want the polished terminal UI without the full optional stack:

```bash
pip install -e ".[tui]"
```

### Prerequisites

- **Python 3.11+** -- [python.org](https://python.org) or `brew install python`
- **Ollama** -- [ollama.com/download](https://ollama.com/download) (for wiki compilation)
- **An Obsidian vault** -- or any directory of Markdown files

## Quick Start

```bash
source .venv/bin/activate

# Bootstrap task system + wiki
./bin/obsidian-legion bootstrap --vault-root ~/my-vault
./bin/obsidian-legion wiki bootstrap --vault-root ~/my-vault

# Add a file and compile your first wiki
cp my-notes.md ~/my-vault/raw/
./bin/obsidian-legion wiki compile --vault-root ~/my-vault

# Or compile from your entire vault
./bin/obsidian-legion wiki compile --vault-wide --vault-root ~/my-vault

# Search your wiki
./bin/obsidian-legion wiki search "any topic" --vault-root ~/my-vault

# Task management
./bin/obsidian-legion capture "My task" \
  --summary "What needs to be done" --vault-root ~/my-vault
./bin/obsidian-legion next --vault-root ~/my-vault
```

## MCP Surface

An optional MCP (Model Context Protocol) server exposes the core verbs as tool
calls via FastMCP -- `capture_task`, `list_tasks`, `next_tasks`, `claim_task`,
`complete_task`, and `refresh_dashboards`. This lets agents that speak MCP
natively interact with Legion without shelling out.

```bash
pip install -e ".[mcp]"
./bin/obsidian-legion-mcp --vault-root <VAULT_ROOT>                          # stdio
./bin/obsidian-legion-mcp --vault-root <VAULT_ROOT> --transport streamable-http
./scripts/setup-claude-mcp.sh   # register with Claude Code
./scripts/setup-gemini-mcp.sh   # register with Gemini CLI
```

## Supported Agents

Legion is agent-agnostic. Any process that can run a shell command or speak MCP
can participate. Tested integrations:

| Agent | Interface | Assignee Label |
|-------|-----------|----------------|
| Codex (CLI/App) | Shell | `codex` |
| Claude Code | Shell or MCP | `claude-code` |
| Gemini CLI | Shell or MCP | `gemini-cli` |
| Ollama (via wrapper) | Shell | `ollama` |
| Human | Obsidian UI | `human` |

See [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) for per-agent rollout
details.

## Related Projects

- **[godhand-lazarus](../godhand-lazarus/)** -- Vector memory and rehydration
  engine. Provides long-term semantic recall across sessions.
- **[hal-tars-blueprint](../hal-tars-blueprint/)** -- Engineering agent
  blueprint. Uses Legion as its task backbone for coordinated multi-agent builds.

## LLM Wiki (Karpathy Pattern)

**New in v0.2.0**: Obsidian Legion now includes an LLM-powered wiki compiler
based on [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

Instead of traditional RAG (stateless retrieval that re-discovers knowledge
every query), the wiki compiler uses an LLM to **compile** raw documents into
persistent, structured wiki articles. The LLM reads once, extracts entities and
themes, writes encyclopedia-style articles with `[[wikilinks]]`, and maintains
an index. The result is a navigable knowledge base that lives in your vault as
plain Markdown.

### 3-Layer Memory Architecture

| Layer | Purpose | Technology |
|-------|---------|------------|
| **1. Obsidian CLI + Legion** | Structured vault access, task coordination | This project |
| **2. LLM Wiki** | Compiled knowledge (NOT stateless retrieval) | Karpathy pattern |
| **3. Lazarus / Qdrant** | Semantic vector fallback for large-scale search | Optional |

### Wiki Quick Start

```bash
# Bootstrap wiki directories
obsidian-legion wiki bootstrap --vault-root <VAULT_ROOT>

# Add raw source files to raw/
cp my-notes.md <VAULT_ROOT>/raw/2026-04-16-my-notes.md

# Compile all pending raw files into wiki articles
obsidian-legion wiki compile --vault-root <VAULT_ROOT>

# Search compiled wiki
obsidian-legion wiki search "consciousness" --vault-root <VAULT_ROOT>

# Check compilation status
obsidian-legion wiki status --vault-root <VAULT_ROOT>
```

### Wiki CLI Reference

| Verb | Description |
|------|-------------|
| `wiki bootstrap` | Create `wiki/` and `raw/` directories with seed files |
| `wiki ingest <path>` | Ingest a specific raw file via LLM compilation |
| `wiki compile` | Compile all new/changed raw files (supports `--dry-run`) |
| `wiki search <query>` | Search wiki articles by title, tags, content |
| `wiki status` | Show compilation stats (raw count, ingested, pending, articles) |
| `wiki list` | List all wiki articles (filter with `--type entity\|topic\|source`) |
| `wiki get <id>` | Show a specific article by slug |

### Wiki Vault Structure

```
<VAULT_ROOT>/
├── raw/                    # Immutable sources (you add files here)
│   └── YYYY-MM-DD-*.md
├── wiki/                   # LLM-compiled knowledge base
│   ├── index.md           # Content catalog
│   ├── log.md             # Append-only event log
│   ├── state.md           # Snapshot state
│   ├── .manifest.json     # Tracks ingested sources
│   ├── entities/          # People, organizations, concepts
│   ├── topics/            # Synthesized thematic articles
│   └── sources/           # Reference stubs
└── 06-daily/action-points/ # Task system (unchanged)
```

### Wiki MCP Tools

The MCP server exposes wiki operations alongside task tools:

| Tool | Description |
|------|-------------|
| `wiki_bootstrap` | Create wiki directories |
| `wiki_ingest` | Ingest a raw file |
| `wiki_compile` | Compile all pending files |
| `wiki_search` | Search wiki articles |
| `wiki_status` | Compilation status |
| `wiki_list` | List articles |

### LLM Configuration

Create `<VAULT_ROOT>/wiki/.wiki_config.yaml` to customize the LLM provider:

```yaml
provider: ollama           # or "claude"
model: llama3.2:3b         # any Ollama model or Claude model ID
ollama_url: http://localhost:11434
```

Defaults to Ollama with `llama3.2:3b`. For Claude, set `ANTHROPIC_API_KEY` in
your environment.

## Development

```bash
cd <VAULT_ROOT>/03-code/active/obsidian-legion
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
pytest
ruff check .
obsidian-legion doctor --vault-root <VAULT_ROOT>
obsidian-legion doctor --format json --vault-root <VAULT_ROOT>
```

## License

Apache 2.0. See [LICENSE](LICENSE).

---

```
╔══════════════════════════════════════════════════════════════╗
║  Built by VALX·VEX — Murphy · HAL-TARS · Alexko Unchained  ║
╚══════════════════════════════════════════════════════════════╝
```

---

Built by one human and three AIs during mass job rejection season.

If this saved you time: [Buy me a coffee](https://buymeacoffee.com/valxvex)
