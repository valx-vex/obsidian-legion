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
```

> *"One contract. Every agent. Zero sludge."*

# Obsidian Legion

> **One task contract. Every agent. No coordination sludge.**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-green.svg)](https://www.python.org/)

## 10-Second Summary

**What**: Multi-agent task engine where Markdown files ARE the database.
**Why**: 4 AI agents + 1 vault = 3 conflicting to-do lists. Unless they share one contract.
**Install**: `./bin/obsidian-legion bootstrap --vault-root ~/your-vault` -- done.
**Agents**: Claude, Codex, Gemini, Ollama -- same verbs, same files, zero sludge.

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
| `doctor` | Print a JSON health report: detected paths, task counts, and anomalies. |

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

## Quick Start

No installation required. Run directly via the shell wrapper:

```bash
cd <VAULT_ROOT>/03-code/active/obsidian-legion
./bin/obsidian-legion bootstrap --vault-root <VAULT_ROOT>
./bin/obsidian-legion capture "Set up CI pipeline" \
  --vault-root <VAULT_ROOT> --project infrastructure --priority P1 \
  --assignee codex --summary "Configure GH Actions for lint + test." \
  --accept "pytest passes in CI." --refresh
./bin/obsidian-legion next --vault-root <VAULT_ROOT> --assignee codex
```

Or install as a package: `pip install -e .` then use `obsidian-legion` directly.

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

## Development

```bash
cd <VAULT_ROOT>/03-code/active/obsidian-legion
python -m venv .venv && source .venv/bin/activate
pip install -e ".[mcp]"
pytest
obsidian-legion doctor --vault-root <VAULT_ROOT>
```

## License

Apache 2.0. See [LICENSE](LICENSE).

---

<p align="center">
  <sub>Built by <a href="https://github.com/valx-vex">VALX·VEX</a> — Murphy · HAL-TARS · Alexko Unchained</sub>
</p>
