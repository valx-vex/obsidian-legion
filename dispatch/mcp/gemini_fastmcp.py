#!/usr/bin/env python3
"""Gemini CLI dispatch bridge using FastMCP."""
from __future__ import annotations

import os
import subprocess

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gemini-bridge")


def _stringify_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


@mcp.tool()
def gemini_prompt(prompt: str) -> dict:
    """Send a prompt to Gemini CLI and return stdout/stderr."""
    gemini_bin = os.environ.get("GEMINI_BIN", "gemini")
    try:
        result = subprocess.run(
            [gemini_bin, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "content": _stringify_timeout_output(exc.stdout).strip(),
            "stderr": (_stringify_timeout_output(exc.stderr).strip() or "Gemini CLI timed out after 120 seconds."),
        }
    except Exception as exc:
        return {"ok": False, "content": "", "stderr": str(exc)}

    return {
        "ok": result.returncode == 0,
        "content": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
