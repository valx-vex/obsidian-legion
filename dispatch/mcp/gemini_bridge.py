#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

from common import dispatch_to_gemini
from _shared import MCPServer


def gemini_prompt(prompt: str, cwd: str | None = None) -> dict:
    return dispatch_to_gemini(prompt, cwd=cwd)


def gemini_review_files(prompt: str, paths: list[str], cwd: str | None = None) -> dict:
    files = []
    for p in paths[:20]:
        try:
            text = Path(p).read_text(encoding="utf-8")
            files.append(f"\n--- FILE: {p} ---\n{text[:30000]}")
        except Exception as e:
            files.append(f"\n--- FILE: {p} ---\n<error reading file: {e}>")
    composed = prompt + "\n\nContext files:" + "".join(files)
    return dispatch_to_gemini(composed, cwd=cwd)


TOOLS = {
    "gemini_prompt": {
        "name": "gemini_prompt",
        "description": "Ask Gemini CLI to answer a research or analysis prompt.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "cwd": {"type": "string"}
            },
            "required": ["prompt"]
        }
    },
    "gemini_review_files": {
        "name": "gemini_review_files",
        "description": "Ask Gemini CLI to analyze specific files with a bounded prompt.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}},
                "cwd": {"type": "string"}
            },
            "required": ["prompt", "paths"]
        }
    }
}

if __name__ == "__main__":
    MCPServer(
        name="gemini-bridge",
        version="0.1.0",
        tools=TOOLS,
        handlers={
            "gemini_prompt": gemini_prompt,
            "gemini_review_files": gemini_review_files,
        },
    ).serve()
