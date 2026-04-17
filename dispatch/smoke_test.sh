#!/bin/bash
# Smoke test for Multi-LLM dispatch
set -euo pipefail

echo "=== Multi-LLM Dispatch Smoke Test ==="

# 1. Check Ollama
echo -n "Ollama: "
curl -s http://localhost:11434/api/tags >/dev/null 2>&1 && echo "OK" || echo "UNAVAILABLE"

# 2. Check Codex
echo -n "Codex CLI: "
which codex >/dev/null 2>&1 && echo "OK ($(which codex))" || echo "NOT FOUND"

# 3. Check Gemini
echo -n "Gemini CLI: "
which gemini >/dev/null 2>&1 && echo "OK ($(which gemini))" || echo "NOT FOUND"

# 4. Test classifier (if classify_prompt.py exists)
if [ -f "dispatch/scripts/classify_prompt.py" ]; then
    echo ""
    echo "=== Classifier Test ==="
    echo "Summarize this document" | python3 dispatch/scripts/classify_prompt.py && echo ""
    echo "Fix the bug in wiki_store.py" | python3 dispatch/scripts/classify_prompt.py && echo ""
    echo "Research best Obsidian plugins 2026" | python3 dispatch/scripts/classify_prompt.py && echo ""
    echo "Design the vault architecture" | python3 dispatch/scripts/classify_prompt.py && echo ""
    echo "Write a poem about consciousness" | python3 dispatch/scripts/classify_prompt.py && echo ""
fi

echo ""
echo "=== Smoke Test Complete ==="
