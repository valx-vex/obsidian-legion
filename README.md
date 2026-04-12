# Obsidian Legion

Obsidian Legion is a vault-native task engine for the Cathedral vault.

It is designed around one hard rule: the source of truth is plain Markdown inside the vault, not a plugin database.

## Why This Exists

The legion already has multiple builders:

- Codex
- Claude Code
- Gemini CLI
- Ollama-backed local agents

The failure mode is obvious: every tool can help, but without one task contract they generate coordination sludge.

Obsidian Legion fixes that by giving every agent the same verbs against the same vault data:

- `bootstrap`
- `capture`
- `list`
- `next`
- `claim`
- `update`
- `done`
- `refresh`
- `doctor`

## Architecture

- Canonical task notes live under `06-daily/action-points/tasks/YYYY/MM/`.
- Human dashboards live under `06-daily/action-points/dashboards/`.
- Human daily rollups live under `06-daily/action-points/daily/YYYY/`.
- Weekly review snapshots live under `06-daily/action-points/reviews/`.
- The action-point registry for agents lives under `06-daily/action-points/config/agents.yaml`.

The engine itself lives here in `03-code/active/obsidian-legion/`.

The official Obsidian CLI is treated as an optional accelerator, not a dependency for correctness. This matters because the official CLI currently expects the Obsidian app to be running.

## Quick Start

Run directly from the repo without installation:

```bash
cd <VAULT_ROOT>/03-code/active/obsidian-legion
./bin/obsidian-legion bootstrap --vault-root ~/cathedral-prime
./bin/obsidian-legion capture "Roll out Obsidian Legion adoption" \
  --vault-root ~/cathedral-prime \
  --project obsidian-legion \
  --area vexnet \
  --priority P1 \
  --assignee codex \
  --summary "Create the shared task contract, dashboards, and first workflow docs." \
  --accept "CLI works against canonical Markdown tasks." \
  --accept "Dashboards render into the vault." \
  --refresh
./bin/obsidian-legion next --vault-root ~/cathedral-prime --assignee codex
```

## Task Contract

Each task note is a Markdown file with YAML frontmatter. Important fields:

- `task_id`: stable ID such as `TASK-20260407-001`
- `status`: `inbox`, `ready`, `in_progress`, `waiting`, `blocked`, `done`, `cancelled`
- `priority`: `P0` to `P3`
- `assignee`: `human`, `codex`, `claude-code`, `gemini-cli`, `ollama`, or another agent label
- `project` and `area`: lightweight coordination tags
- `summary`: plain language mission statement
- `acceptance`: explicit done-criteria list
- `log`: timestamped task history

## MCP Surface

An optional MCP server is included. It exposes the same task verbs through `FastMCP`.

If the `mcp` package is missing, the server exits with a direct instruction instead of failing vaguely.

Run it with:

```bash
cd <VAULT_ROOT>/03-code/active/obsidian-legion
./bin/obsidian-legion-mcp --vault-root ~/cathedral-prime
```

## Agent Usage Pattern

Every agent should follow the same flow:

1. `next --assignee <agent>`
2. `claim TASK-... --assignee <agent>`
3. work
4. `done TASK-...` or `update TASK-... --status waiting|blocked`
5. `refresh`

That keeps the human UI and the machine state aligned.

Rollout notes for Codex, Claude Code, Gemini CLI, and Ollama live in `docs/INTEGRATIONS.md`.
