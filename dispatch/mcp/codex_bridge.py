#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

from common import dispatch_to_codex
from _shared import MCPServer


def codex_exec(prompt: str, cwd: str | None = None) -> dict:
    return dispatch_to_codex(prompt, cwd=cwd)


def codex_patch(prompt: str, cwd: str | None = None, output_schema: str | None = None) -> dict:
    return dispatch_to_codex(prompt, cwd=cwd, output_schema=output_schema)


TOOLS = {
    "codex_exec": {
        "name": "codex_exec",
        "description": "Run a bounded coding task with Codex CLI.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "cwd": {"type": "string"}
            },
            "required": ["prompt"]
        }
    },
    "codex_patch": {
        "name": "codex_patch",
        "description": "Ask Codex CLI for a patch or structured coding output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "cwd": {"type": "string"},
                "output_schema": {"type": "string"}
            },
            "required": ["prompt"]
        }
    }
}

if __name__ == "__main__":
    MCPServer(
        name="codex-bridge",
        version="0.1.0",
        tools=TOOLS,
        handlers={
            "codex_exec": codex_exec,
            "codex_patch": codex_patch,
        },
    ).serve()
