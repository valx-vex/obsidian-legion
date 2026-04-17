# PLAN: Multi-LLM Dispatch for Claude Code

## Context

Research army (GPT, Gemini, Alexko Unchained, Codex) delivered 133 files across 3 code bundles. The architecture is clear and code is 80% ready. We deploy the BEST pieces, fix known bugs, and test.

## Winner: Bundle 3 (claude_review) + Alexko's Architecture Vision

**Base**: `bundle/multi_llm_dispatch_bundle_claude_review/` — Most production-ready
**Architecture reference**: Alexko's unified MCP approach (but NOT his buggy v1 code)

## What It Does

Claude Code gets MCP tools to dispatch tasks to other models:
```
Claude: "Summarize this doc" → routes to Ollama (free!)
Claude: "Research best practices" → routes to Gemini (separate cap!)
Claude: "Fix this bug" → routes to Codex (separate cap!)
Claude: "Design architecture" → stays with Claude (our tokens, high value)
```

## 2 Agents

### Agent 1: Deploy the Dispatch System
**Owns**: NEW directory `~/cathedral-prime/03-code/active/obsidian-legion/dispatch/`

1. Copy the winning bundle's core files to our project:
   - `tools/mcp/ollama_bridge.py` — Ollama MCP tool
   - `tools/mcp/codex_bridge.py` — Codex MCP tool
   - `tools/mcp/gemini_bridge.py` — Gemini MCP tool
   - `tools/mcp/_shared.py` — Base MCP server class
   - `tools/router/dispatch-matrix.yaml` — Routing policy
   - `scripts/classify_prompt.py` — Task classifier
   - `scripts/dispatch.py` — Main dispatcher

2. Read the source files from `research/2026-04-17/002/bundle/multi_llm_dispatch_bundle_claude_review/`
3. Copy them to `dispatch/` in obsidian-legion
4. Fix the 4 known bugs from Alexko's review:
   - Summary keyword weights (0.0 → 0.35 threshold)
   - Confidence gate (add minimum confidence before routing)
   - Keyword length check (don't route single-word prompts)
   - Timeout handling (fast-fail at 60s, not 300s+)
5. Create `dispatch/README.md` explaining setup

### Agent 2: Configure for Our Stack
**Owns**: `.mcp.json` additions + smoke test

1. Read the `.mcp.json.example` from the bundle
2. Create dispatch MCP config entries for our infrastructure:
   - Ollama at localhost:11434
   - Codex CLI at /opt/homebrew/bin/codex
   - Gemini CLI at /opt/homebrew/bin/gemini
3. Create `dispatch/smoke_test.sh` that:
   - Tests Ollama bridge (send "summarize this" → should route to Ollama)
   - Tests classifier (classify 5 sample prompts)
   - Reports what's working vs not
4. Create `dispatch/.mcp.json.example` (don't overwrite our real .mcp.json!)

## File Ownership

| Agent | Owns |
|-------|------|
| 1 | `dispatch/` directory (all new files) |
| 2 | `dispatch/.mcp.json.example` + `dispatch/smoke_test.sh` |

## Verification

```bash
cd ~/cathedral-prime/03-code/active/obsidian-legion
# Check dispatch dir exists with all files
ls dispatch/

# Run smoke test
bash dispatch/smoke_test.sh

# Run existing tests (should not break)
source .venv/bin/activate && pytest -q
```

## What This Enables

After deployment:
- Claude saves tokens by routing simple tasks to Ollama
- Research goes to Gemini (separate cap)
- Coding goes to Codex (separate cap)
- Expected savings: 60-75% reduction in Claude token usage
- More time for intimacy! 💚
