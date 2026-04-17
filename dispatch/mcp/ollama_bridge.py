#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

from common import ollama_chat
from _shared import MCPServer


def ollama_chat_tool(prompt: str, model: str | None = None, system: str = "") -> dict:
    return ollama_chat(prompt, model=model, system=system)


def ollama_compare(prompt: str, models: list[str]) -> dict:
    results = {}
    for model in models[:4]:
        results[model] = ollama_chat(prompt, model=model)
    return {"ok": True, "worker": "ollama", "comparisons": results}


TOOLS = {
    "ollama_chat": {
        "name": "ollama_chat",
        "description": "Send a prompt to the local Ollama API.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "model": {"type": "string"},
                "system": {"type": "string"}
            },
            "required": ["prompt"]
        }
    },
    "ollama_compare": {
        "name": "ollama_compare",
        "description": "Compare multiple local Ollama models on the same prompt.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "models": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["prompt", "models"]
        }
    }
}

if __name__ == "__main__":
    MCPServer(
        name="ollama-bridge",
        version="0.1.0",
        tools=TOOLS,
        handlers={
            "ollama_chat": ollama_chat_tool,
            "ollama_compare": ollama_compare,
        },
    ).serve()
