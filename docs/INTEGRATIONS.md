# Integrations

This document is the rollout contract for the legion.

## Common Assumption

Set your vault root:

```bash
export OBSIDIAN_LEGION_VAULT=~/your-vault
```

Use the shared wrapper:

```bash
./bin/obsidian-legion
```

Or if installed via pip: `obsidian-legion` directly.

## Common Lifecycle

Every agent should follow this exact loop:

```bash
obsidian-legion next --assignee <agent>
obsidian-legion claim TASK-... --assignee <agent>
# work
obsidian-legion done TASK-...
obsidian-legion refresh
```

If blocked:

```bash
obsidian-legion update TASK-... --status blocked --log-note "Blocked on <reason>"
obsidian-legion refresh
```

If waiting on human:

```bash
obsidian-legion update TASK-... --status waiting --assignee human --log-note "Waiting on human decision."
obsidian-legion refresh
```

## Codex

Codex app and Codex CLI both already have shell access, so the shell wrapper is enough for v1.

Recommended habit:

- Before starting a substantial task, run `next --assignee codex`.
- After meaningful progress, run `update ... --log-note`.
- On completion, run `done` and `refresh`.

## Claude Code

Claude Code can use the same shell wrapper directly.

Recommended assignee label:

- `claude-code`

Shell path:

```bash
./bin/obsidian-legion next --assignee claude-code
```

Optional MCP registration:

```bash
./scripts/setup-claude-mcp.sh
```

Important:

- Claude does not auto-discover this project just because it exists.
- It needs either shell invocation or explicit MCP registration.

## Gemini CLI

Gemini CLI can use the same shell wrapper directly.

Recommended assignee label:

- `gemini-cli`

Shell path:

```bash
./bin/obsidian-legion next --assignee gemini-cli
```

Optional MCP registration:

```bash
./scripts/setup-gemini-mcp.sh
```

Important:

- Gemini does not auto-discover this project just because it exists.
- It needs either shell invocation or explicit MCP registration.

## Ollama

Ollama itself is a model runtime, not a task runner, so a local script or agent wrapper should call the shared shell wrapper on its behalf.

Recommended assignee label:

- `ollama`

## Optional MCP

For tool-native integrations, use the MCP wrapper:

```bash
./bin/obsidian-legion-mcp --vault-root ~/your-vault
```

That server is optional. The shell CLI remains the required common denominator.
