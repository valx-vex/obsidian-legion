#!/usr/bin/env python3
"""Codex CLI dispatch bridge using FastMCP."""
from __future__ import annotations

import os
import subprocess

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("codex-bridge")


def _stringify_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


@mcp.tool()
def codex_exec(prompt: str, timeout_seconds: int = 120) -> dict:
    """Send a prompt to Codex CLI over stdin and return stdout/stderr."""
    codex_bin = os.environ.get("CODEX_BIN", "codex")
    effective_timeout = max(120, timeout_seconds)

    try:
        result = subprocess.run(
            [codex_bin, "exec"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "content": _stringify_timeout_output(exc.stdout),
            "stderr": (_stringify_timeout_output(exc.stderr) or f"Codex CLI timed out after {effective_timeout} seconds."),
            "timeout_seconds": effective_timeout,
        }
    except Exception as exc:
        return {
            "ok": False,
            "content": "",
            "stderr": str(exc),
            "timeout_seconds": effective_timeout,
        }

    return {
        "ok": result.returncode == 0,
        "content": result.stdout,
        "stderr": result.stderr,
        "timeout_seconds": effective_timeout,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
