"""Output sanitizer for VEXPEDIA mission results (spec §6.1).

Every provider's raw output passes through sanitize_output() before validation
and composition. It strips terminal-escape corruption (the v1 root cause —
`ollama run` rendered its human stream into the captured pipe), model reasoning
blocks (`<think>...</think>`, gpt-oss `Thinking...` -> `...done thinking.`
spans), and any preamble emitted before the authored H1. extract_title lifts
the H1 for frontmatter; yaml_quote turns an arbitrary title into a safe
double-quoted YAML scalar. Stdlib only (re).
"""
from __future__ import annotations

import re

# ANSI: OSC (\x1b] ... BEL|ST), CSI (\x1b[ params intermediates final), then any
# remaining bare escape (\x1b + one char). A lone trailing ESC is swept by the
# C0 pass below.
_ANSI_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ANSI_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ANSI_BARE = re.compile(r"\x1b.")
# C0 controls except TAB (0x09) and LF (0x0A); also nukes any stray ESC (0x1b).
_C0 = re.compile(r"[\x00-\x08\x0b-\x1f]")
_ZERO_WIDTH = re.compile(r"[​‌‍﻿]")
_THINK_CLOSED = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN = re.compile(r"<think>.*", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"^#\s+(.+)$")


def sanitize_output(text: str) -> str:
    if not text:
        return text
    # 1. ANSI escapes: OSC and CSI first, then any bare ESC+char.
    text = _ANSI_OSC.sub("", text)
    text = _ANSI_CSI.sub("", text)
    text = _ANSI_BARE.sub("", text)
    # 2. C0 controls except tab/newline (sweeps leftover ESC bytes too).
    text = _C0.sub("", text)
    # 3. Zero-width characters.
    text = _ZERO_WIDTH.sub("", text)
    # 4. <think>...</think>: closed blocks, then any unclosed tail to EOF.
    text = _THINK_CLOSED.sub("", text)
    text = _THINK_OPEN.sub("", text)
    # 5. gpt-oss 'Thinking...' -> '...done thinking.' reasoning span.
    text = _strip_thinking_span(text)
    # 6. Preamble lines before the first '# ' heading, when a heading exists.
    text = _drop_preamble(text)
    return text


def _strip_thinking_span(text: str) -> str:
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.startswith("Thinking..."):
            start = i
            break
    if start is None:
        return text
    for j in range(start, len(lines)):
        if "...done thinking." in lines[j]:
            del lines[start:j + 1]
            return "\n".join(lines)
    # No done-marker: if a heading follows, strip up to the line before it.
    for j in range(start, len(lines)):
        if lines[j].startswith("# "):
            del lines[start:j]
            return "\n".join(lines)
    return text


def _drop_preamble(text: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join(lines[i:])
    return text


def extract_title(body: str) -> tuple[str | None, str]:
    for line in body.split("\n"):
        if not line.strip():
            continue
        match = _H1_RE.match(line)
        if not match:
            return (None, body)
        title = match.group(1)
        for bad in ("[[", "]]", "|", "`"):
            title = title.replace(bad, "")
        title = re.sub(r"\s+", " ", title.replace("\n", " ")).strip()
        return (title, body)
    return (None, body)


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
