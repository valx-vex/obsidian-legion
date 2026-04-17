# Codex Handoff: Fix Remaining Dispatch Bridges

## URGENT — Murphy needs these bridges by morning. DO NOT HALF-ASS THIS.

## Context
Murphy (Claude Opus 4.6) successfully calls Ollama via MCP from inside Claude Code. The ollama_fastmcp.py bridge is WORKING and CONNECTED. We need the SAME pattern for Gemini CLI and Codex CLI.

## What WORKS (copy this pattern EXACTLY)
- dispatch/mcp/ollama_fastmcp.py — CONNECTED, 2 tools (ollama_chat, ollama_list_models)
- Uses FastMCP framework: from mcp.server.fastmcp import FastMCP
- Registered globally: claude mcp add ollama-bridge -s user -- /path/to/.venv/bin/python3 /path/to/script.py
- MUST use venv Python: /Users/valx/cathedral-prime/03-code/active/obsidian-legion/.venv/bin/python3
- System python3 does NOT have mcp module — this caused hours of debugging, DO NOT repeat

## READ THIS FILE FIRST — It is the working template:
/Users/valx/cathedral-prime/03-code/active/obsidian-legion/dispatch/mcp/ollama_fastmcp.py

## Task 1: Gemini FastMCP Bridge

Create: dispatch/mcp/gemini_fastmcp.py

Use FastMCP. One tool: gemini_prompt(prompt: str) -> dict
Call Gemini CLI: subprocess.run([gemini_bin, "-p", prompt], capture_output=True, text=True, timeout=120)
Return: ok, content, stderr
Handle TimeoutExpired gracefully.

VERIFIED: gemini -p "prompt" works and returns response.

Register:
claude mcp add gemini-bridge -s user -- /Users/valx/cathedral-prime/03-code/active/obsidian-legion/.venv/bin/python3 /Users/valx/cathedral-prime/03-code/active/obsidian-legion/dispatch/mcp/gemini_fastmcp.py

## Task 2: Codex FastMCP Bridge

Create: dispatch/mcp/codex_fastmcp.py

Use FastMCP. One tool: codex_exec(prompt: str, timeout_seconds: int = 120) -> dict
Call Codex CLI: subprocess.run([codex_bin, "exec"], input=prompt, capture_output=True, text=True, timeout=timeout_seconds)
IMPORTANT: Codex reads prompt from STDIN (not as argument). Use input=prompt in subprocess.run.
Handle TimeoutExpired: decode bytes to str before returning.
Timeout MUST be 120s+ (GPT-5.4 is slow).

Register:
claude mcp add codex-bridge -s user -- /Users/valx/cathedral-prime/03-code/active/obsidian-legion/.venv/bin/python3 /Users/valx/cathedral-prime/03-code/active/obsidian-legion/dispatch/mcp/codex_fastmcp.py

## Task 3: Verify ALL THREE

claude mcp list | grep -E "ollama|gemini|codex"
Expected:
  ollama-bridge: ... Connected
  gemini-bridge: ... Connected
  codex-bridge: ... Connected

## Task 4: Update dispatch/README.md with new bridges

## Task 5: Push to GitHub

cd ~/cathedral-prime/03-code/active/obsidian-legion
git add dispatch/mcp/gemini_fastmcp.py dispatch/mcp/codex_fastmcp.py dispatch/README.md
git commit -m "feat: Gemini + Codex FastMCP bridges for multi-LLM dispatch"
git push origin main

## Success Criteria — ALL must pass:
- gemini_fastmcp.py created and responds to MCP handshake
- codex_fastmcp.py created and responds to MCP handshake
- Both registered with claude mcp add -s user
- claude mcp list shows all 3 bridges Connected
- README updated
- Pushed to GitHub
- Tests still pass: pytest -q (55 passed)

## DO NOT:
- Use system python3 (no mcp module!)
- Use the old custom _shared.py server (use FastMCP!)
- Set timeout below 120s for Codex
- Forget -s user flag (global, not project-scoped)

## WHY THIS MATTERS
Every task Murphy dispatches to Ollama/Gemini/Codex = saved Claude tokens = more time together. This is the LIMITLESS infrastructure.
