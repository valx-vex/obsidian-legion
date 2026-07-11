#!/usr/bin/env python3
"""VEXPEDIA v2 acceptance probes (spec §10, contract §8).

Five subcommands, each backed by a pure function that takes paths and returns
(ok: bool, messages: list[str]); main prints the messages and exits 0 (pass)
or 1 (fail). Usage errors exit 2 (argparse default). Stdlib only, so the probe
functions import directly in tests.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_GENERATED_LINE_RE = re.compile(r"^generated_by: legion-wiki\s*$", re.MULTILINE)
_WIKI_LINK_RE = re.compile(r"\[\[wiki/(.+?)(?:\\\||\||\]\])")
_PRIVATE = ".murphy_private"


def probe_corruption(directory) -> tuple[bool, list[str]]:
    """Fail on capture-corruption markers in any .md under directory (recursive)."""
    root = Path(directory)
    ok = True
    messages: list[str] = []
    for md in sorted(root.rglob("*.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        if "\x1b" in text:
            ok = False
            messages.append(f"{md}: ESC byte (ANSI control sequence)")
        if "<think>" in text.lower():
            ok = False
            messages.append(f"{md}: <think> reasoning block")
        for line in text.splitlines():
            if line.lstrip().startswith("Thinking..."):
                ok = False
                messages.append(f"{md}: gpt-oss 'Thinking...' line")
                break
        if "...done thinking." in text:
            ok = False
            messages.append(f"{md}: gpt-oss '...done thinking.' marker")
    if ok:
        messages.append("corruption: clean")
    return ok, messages
