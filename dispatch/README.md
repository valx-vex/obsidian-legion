# Multi-LLM Dispatch System

Route prompts to the cheapest capable worker: Ollama, Gemini CLI, Codex CLI, or Claude.

## What this is

A staged hybrid dispatch layer for Obsidian Legion. Claude Code stays the orchestrator. The canonical MCP path is now FastMCP bridge scripts launched with the project venv Python and registered in Claude Code with `-s user`.

## Canonical MCP Bridge Path

Use these FastMCP bridge scripts:

- `dispatch/mcp/ollama_fastmcp.py`
- `dispatch/mcp/gemini_fastmcp.py`
- `dispatch/mcp/codex_fastmcp.py`

Use this Python exactly:

`/Users/valx/cathedral-prime/03-code/active/obsidian-legion/.venv/bin/python3`

Do not use system `python3` for these bridges. The project venv has the `mcp.server.fastmcp` dependency; system Python does not.

## User-Scoped Claude Registration

Register the bridges globally for Claude Code with these exact commands:

```bash
claude mcp add ollama-bridge -s user -- \
  /Users/valx/cathedral-prime/03-code/active/obsidian-legion/.venv/bin/python3 \
  /Users/valx/cathedral-prime/03-code/active/obsidian-legion/dispatch/mcp/ollama_fastmcp.py

claude mcp add gemini-bridge -s user -- \
  /Users/valx/cathedral-prime/03-code/active/obsidian-legion/.venv/bin/python3 \
  /Users/valx/cathedral-prime/03-code/active/obsidian-legion/dispatch/mcp/gemini_fastmcp.py

claude mcp add codex-bridge -s user -- \
  /Users/valx/cathedral-prime/03-code/active/obsidian-legion/.venv/bin/python3 \
  /Users/valx/cathedral-prime/03-code/active/obsidian-legion/dispatch/mcp/codex_fastmcp.py
```

Verify:

```bash
claude mcp list | grep -E "ollama|gemini|codex"
```

Expected end state:

- `ollama-bridge` -> Connected
- `gemini-bridge` -> Connected
- `codex-bridge` -> Connected

## Directory Layout

```text
dispatch/
├── README.md
├── mcp/
│   ├── ollama_fastmcp.py       # canonical Ollama FastMCP bridge
│   ├── gemini_fastmcp.py       # canonical Gemini FastMCP bridge
│   ├── codex_fastmcp.py        # canonical Codex FastMCP bridge
│   ├── ollama_bridge.py        # legacy custom JSON-RPC bridge
│   ├── gemini_bridge.py        # legacy custom JSON-RPC bridge
│   ├── codex_bridge.py         # legacy custom JSON-RPC bridge
│   └── _shared.py              # legacy base server
├── router/
│   └── dispatch-matrix.yaml
└── scripts/
    ├── common.py
    ├── classify_prompt.py
    └── dispatch.py
```

## Legacy Notes

The `_shared.py` bridge family remains in the repo for now to minimize churn, but it is not the preferred Claude MCP setup anymore. If you want the working Claude-facing bridge path, use the FastMCP scripts above.

## Dispatch Matrix

| Route   | Use for                                                | Escalates to |
|---------|--------------------------------------------------------|--------------|
| ollama  | summarization, rewriting, wiki normalization, low-risk transforms | gemini |
| gemini  | repo research, long-context analysis, broad questions  | claude       |
| codex   | bounded implementation, patches, refactor attempts     | claude       |
| claude  | architecture, acceptance review, risky or ambiguous work | --         |
| n8n     | phase 2 queued jobs, scheduled jobs, retries           | --           |

## Bridge Behavior

### Ollama FastMCP

- Tool: `ollama_chat`
- Tool: `ollama_list_models`
- Transport: stdio

### Gemini FastMCP

- Tool: `gemini_prompt(prompt: str) -> dict`
- Backend: `gemini -p <prompt>`
- Timeout: 120 seconds

### Codex FastMCP

- Tool: `codex_exec(prompt: str, timeout_seconds: int = 120) -> dict`
- Backend: `codex exec`
- Prompt delivery: stdin
- Timeout: minimum 120 seconds

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base URL |
| `OLLAMA_DEFAULT_MODEL` | `llama3.2:3b` | Default Ollama model for FastMCP bridge |
| `GEMINI_BIN` | `gemini` | Gemini CLI path for FastMCP bridge |
| `CODEX_BIN` | `codex` | Codex CLI path for FastMCP bridge |
| `DISPATCH_LOG_DIR` | `dispatch/.logs` | JSONL route logs for the dispatcher |
| `DISPATCH_POLICY_PATH` | `dispatch/router/dispatch-matrix.yaml` | Custom policy file |

## How to Test

### 1. Verify FastMCP import in the project venv

```bash
/Users/valx/cathedral-prime/03-code/active/obsidian-legion/.venv/bin/python3 -c \
  "from mcp.server.fastmcp import FastMCP; print('fastmcp ok')"
```

### 2. Smoke-test the CLI assumptions

```bash
gemini -p "Reply with exactly GEMINI_OK"
printf 'Reply with exactly CODEX_OK\n' | codex exec
```

### 3. Verify repo tests still pass

```bash
cd ~/cathedral-prime/03-code/active/obsidian-legion
source .venv/bin/activate
pytest -q
```

## Infrastructure Defaults

- Ollama URL: `http://localhost:11434`
- Light Ollama model: `llama3.2:3b`
- Claude remains the orchestrator and acceptance judge
