# Integrations

This document is the rollout contract for the legion.

## Common Assumption

Use the canonical vault root:

```bash
export OBSIDIAN_LEGION_VAULT=/Users/valx/cathedral-prime
```

Use the shared wrapper:

```bash
/Users/valx/cathedral-prime/03-code/active/obsidian-legion/bin/obsidian-legion
```

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
/Users/valx/cathedral-prime/03-code/active/obsidian-legion/bin/obsidian-legion next --assignee claude-code
```

Optional MCP registration:

```bash
/Users/valx/cathedral-prime/03-code/active/obsidian-legion/scripts/setup-claude-mcp.sh
```

Important:

- Claude does not auto-discover this project just because it exists.
- It needs either shell invocation or explicit MCP registration.
- On `VexNet_003` / VexNet003 M3, `obsidian-legion` has already been registered.

## Gemini CLI

Gemini CLI can use the same shell wrapper directly.

Recommended assignee label:

- `gemini-cli`

Shell path:

```bash
/Users/valx/cathedral-prime/03-code/active/obsidian-legion/bin/obsidian-legion next --assignee gemini-cli
```

Optional MCP registration:

```bash
/Users/valx/cathedral-prime/03-code/active/obsidian-legion/scripts/setup-gemini-mcp.sh
```

Important:

- Gemini does not auto-discover this project just because it exists.
- It needs either shell invocation or explicit MCP registration.
- On `VexNet_003` / VexNet003 M3, `obsidian-legion` has already been registered at user scope.

## Ollama

Ollama itself is a model runtime, not a task runner, so a local script or agent wrapper should call the shared shell wrapper on its behalf.

Recommended assignee label:

- `ollama`

## Optional MCP

For tool-native integrations, use the MCP wrapper:

```bash
/Users/valx/cathedral-prime/03-code/active/obsidian-legion/bin/obsidian-legion-mcp --vault-root /Users/valx/cathedral-prime
```

That server is optional. The shell CLI remains the required common denominator.
