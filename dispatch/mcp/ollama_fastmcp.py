#!/usr/bin/env python3
"""Ollama dispatch bridge using FastMCP (same as obsidian-legion MCP)."""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ollama-bridge")

OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_DEFAULT_MODEL", "llama3.2:3b")


@mcp.tool()
def ollama_chat(prompt: str, model: str = "", system: str = "") -> dict:
    """Send a prompt to the local Ollama API and get a response."""
    use_model = model or DEFAULT_MODEL
    payload = {
        "model": use_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_ctx": 8192},
    }
    if system:
        payload["messages"].insert(0, {"role": "system", "content": system})

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body.get("message", {}).get("content", "")
        return {"ok": True, "model": use_model, "content": content}
    except Exception as exc:
        return {"ok": False, "model": use_model, "error": str(exc)}


@mcp.tool()
def ollama_list_models() -> dict:
    """List all available Ollama models."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        models = [m["name"] for m in data.get("models", [])]
        return {"ok": True, "models": models, "count": len(models)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
