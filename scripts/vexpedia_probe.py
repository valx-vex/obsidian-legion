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


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter, body); ('', text) when there is no --- frontmatter."""
    if not text.lstrip().startswith("---"):
        return "", text
    parts = text.split("---")
    if len(parts) < 3:
        return "", text
    return parts[1], "---".join(parts[2:])


def _parse_sources(frontmatter: str) -> list[str]:
    """Read the `sources:` YAML list items out of a frontmatter block."""
    sources: list[str] = []
    in_sources = False
    for line in frontmatter.splitlines():
        if re.match(r"^sources:\s*$", line):
            in_sources = True
            continue
        if not in_sources:
            continue
        item = re.match(r"^\s+-\s+(.+?)\s*$", line)
        if item:
            sources.append(item.group(1))
        elif line.strip() == "":
            continue
        else:
            break                       # the next top-level key ends the block
    return sources


def _private_names(vault_root: Path) -> set[str]:
    """Basenames AND stems of every file under any `.murphy_private` dir."""
    names: set[str] = set()
    for private_dir in vault_root.rglob(_PRIVATE):
        if not private_dir.is_dir():
            continue
        for f in private_dir.rglob("*"):
            if f.is_file():
                names.add(f.name)
                names.add(f.stem)
    names.discard("")
    return names


def probe_privacy(vault_root) -> tuple[bool, list[str]]:
    """Three-part content-surface privacy probe (spec §9.6)."""
    root = Path(vault_root)
    wiki = root / "wiki"
    private_names = _private_names(root)
    ok = True
    messages: list[str] = []
    for md in sorted(wiki.rglob("*.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        frontmatter, body = _split_frontmatter(text)
        sources = _parse_sources(frontmatter)
        # (a) no source path may live under .murphy_private
        for src in sources:
            if _PRIVATE in src:
                ok = False
                messages.append(f"{md}: private source listed: {src}")
        # (b) no private basename/stem may surface anywhere in the page
        for name in private_names:
            if name in text:
                ok = False
                messages.append(f"{md}: private name surfaced: {name}")
        # (c) a literal .murphy_private in the body must trace to a listed source
        if _PRIVATE in body:
            traceable = False
            for src in sources:
                try:
                    src_text = (root / src).read_text(
                        encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if _PRIVATE in src_text:
                    traceable = True
                    break
            if not traceable:
                ok = False
                messages.append(
                    f"{md}: untraceable .murphy_private literal in body")
    if ok:
        messages.append("privacy: clean")
    return ok, messages
