# Multi-LLM Dispatch System

Route prompts to the cheapest capable worker: Ollama (local), Gemini CLI, Codex CLI, or Claude.

## What this is

A staged hybrid dispatch layer for Obsidian Legion. Claude Code stays the orchestrator. Explicit MCP bridge tools provide the first delegation path. Hooks run in shadow mode only for classification and policy logging.

## Directory layout

```
dispatch/
├── README.md                    # This file
├── mcp/
│   ├── __init__.py
│   ├── _shared.py              # Base MCP server (JSON-RPC over stdio)
│   ├── ollama_bridge.py        # ollama_chat, ollama_compare
│   ├── codex_bridge.py         # codex_exec, codex_patch
│   └── gemini_bridge.py        # gemini_prompt, gemini_review_files
├── router/
│   └── dispatch-matrix.yaml    # Routing policy (what goes where)
└── scripts/
    ├── common.py               # Shared utils, classify_prompt, worker functions
    ├── classify_prompt.py      # Shadow hook: classify + log route hint
    └── dispatch.py             # CLI dispatcher: auto-route or explicit route
```

## Dispatch matrix

| Route   | Use for                                               | Escalates to |
|---------|-------------------------------------------------------|--------------|
| ollama  | summarization, rewriting, wiki normalization, low-risk | gemini       |
| gemini  | repo research, long-context analysis, broad questions  | claude       |
| codex   | bounded implementation, patches, refactor attempts     | claude       |
| claude  | architecture, acceptance review, risky/ambiguous work  | --           |
| n8n     | (phase 2) queued jobs, scheduled jobs, retries         | --           |

## How to enable

### 1. MCP bridges

Add to your `.mcp.json` or Claude Code MCP config:

```json
{
  "mcpServers": {
    "ollama-bridge": {
      "command": "python3",
      "args": ["dispatch/mcp/ollama_bridge.py"],
      "cwd": "<repo-root>"
    },
    "codex-bridge": {
      "command": "python3",
      "args": ["dispatch/mcp/codex_bridge.py"],
      "cwd": "<repo-root>"
    },
    "gemini-bridge": {
      "command": "python3",
      "args": ["dispatch/mcp/gemini_bridge.py"],
      "cwd": "<repo-root>"
    }
  }
}
```

### 2. Shadow hook (optional)

To log route classification on every user prompt:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "type": "command",
        "command": "python3 dispatch/scripts/classify_prompt.py"
      }
    ]
  }
}
```

### 3. Environment variables

| Variable                      | Default                    | Description                    |
|-------------------------------|----------------------------|--------------------------------|
| `OLLAMA_BASE_URL`             | `http://localhost:11434`   | Ollama API base URL            |
| `OLLAMA_MODEL_DEFAULT`        | `llama3.2:3b`             | Default light model            |
| `DISPATCH_CONFIDENCE_THRESHOLD` | `0.35`                   | Min confidence to route away from Claude |
| `DISPATCH_LOG_DIR`            | `dispatch/.logs`           | Where JSONL logs are written   |
| `DISPATCH_POLICY_PATH`        | `dispatch/router/dispatch-matrix.yaml` | Custom policy file |
| `GEMINI_CLI_BIN`              | `gemini`                   | Path to Gemini CLI             |
| `CODEX_CLI_BIN`               | `codex`                    | Path to Codex CLI              |

## How to test

### CLI dispatcher

```bash
# Auto-route (classifier picks the worker)
python3 dispatch/scripts/dispatch.py "summarize this document"

# Force a specific route
python3 dispatch/scripts/dispatch.py --route ollama "rewrite this paragraph"

# Use a heavier Ollama model
python3 dispatch/scripts/dispatch.py --route ollama --ollama-model qwen3.5:27b "explain this code"

# Route to Gemini for research
python3 dispatch/scripts/dispatch.py --route gemini "analyze the repo structure"
```

### Shadow classifier

```bash
echo '{"prompt": "summarize this file"}' | python3 dispatch/scripts/classify_prompt.py
```

### Verify existing tests still pass

```bash
cd ~/cathedral-prime/03-code/active/obsidian-legion
source .venv/bin/activate
pytest -q
```

## Bug fixes applied (vs. research bundle)

1. **Minimum keyword length**: `classify_prompt` now skips single-character keywords to avoid false substring matches.
2. **Confidence threshold**: Routes below 0.35 confidence fall back to Claude instead of routing to a cheaper worker.
3. **Summary weights**: `dispatch-matrix.yaml` routes now have explicit `weight` values (were missing).
4. **Timeout cap**: All subprocess and HTTP timeouts capped at 60 seconds (were 120-1800s in source).

## Infrastructure defaults

- Ollama URL: `http://localhost:11434`
- Light model: `llama3.2:3b`
- Heavy model: `qwen3.5:27b` (pass via `--ollama-model`)
