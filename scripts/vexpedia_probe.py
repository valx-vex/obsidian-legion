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


def _is_generated(text: str) -> bool:
    return bool(_GENERATED_LINE_RE.search(text))


def _generated_disk_pages(wiki: Path) -> set[str]:
    """Relpaths (topics/..., entities/...) of generated pages on disk."""
    pages: set[str] = set()
    for sub in ("topics", "entities"):
        directory = wiki / sub
        if not directory.exists():
            continue
        for page in directory.glob("*.md"):
            if _is_generated(page.read_text(encoding="utf-8", errors="replace")):
                pages.add(f"{sub}/{page.name}")
    return pages


def probe_index(vault_root) -> tuple[bool, list[str]]:
    """index.md links must equal the generated pages on disk, both directions."""
    root = Path(vault_root)
    wiki = root / "wiki"
    index = wiki / "index.md"
    if not index.exists():
        return False, [f"index: missing {index}"]
    listed = set(_WIKI_LINK_RE.findall(
        index.read_text(encoding="utf-8", errors="replace")))
    on_disk = _generated_disk_pages(wiki)
    ghost = listed - on_disk
    missing = on_disk - listed
    ok = not ghost and not missing
    messages: list[str] = []
    if ghost:
        messages.append(f"index: links to absent pages: {sorted(ghost)}")
    if missing:
        messages.append(f"index: disk pages not listed: {sorted(missing)}")
    if ok:
        messages.append(f"index: exact match ({len(on_disk)} pages)")
    return ok, messages


def probe_deadlinks(vault_root) -> tuple[bool, list[str]]:
    """No [[wiki/...]] link in a generated page may resolve to a missing file."""
    root = Path(vault_root)
    wiki = root / "wiki"
    ok = True
    messages: list[str] = []
    for sub in ("topics", "entities"):
        directory = wiki / sub
        if not directory.exists():
            continue
        for page in sorted(directory.glob("*.md")):
            text = page.read_text(encoding="utf-8", errors="replace")
            if not _is_generated(text):
                continue
            for target in _WIKI_LINK_RE.findall(text):
                if not (wiki / target).exists():
                    ok = False
                    messages.append(
                        f"{sub}/{page.name}: dead link -> wiki/{target}")
    if ok:
        messages.append("deadlinks: none")
    return ok, messages


def _wiki_relpaths(vault_root: Path) -> set[str]:
    wiki = vault_root / "wiki"
    if not wiki.exists():
        return set()
    return {str(p.relative_to(wiki)) for p in wiki.rglob("*.md")}


def probe_mobile(src_vault, dest_vault) -> tuple[bool, list[str]]:
    """The set of wiki/**.md relpaths must be identical on both sides."""
    src = _wiki_relpaths(Path(src_vault))
    dest = _wiki_relpaths(Path(dest_vault))
    missing = src - dest
    extra = dest - src
    ok = not missing and not extra
    messages: list[str] = []
    if missing:
        messages.append(f"mobile: dest missing: {sorted(missing)}")
    if extra:
        messages.append(f"mobile: dest extra: {sorted(extra)}")
    if ok:
        messages.append(f"mobile: {len(src)} pages match")
    return ok, messages


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="vexpedia_probe",
        description="VEXPEDIA v2 acceptance probes (spec §10)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_corr = sub.add_parser("corruption")
    p_corr.add_argument("dir")

    p_priv = sub.add_parser("privacy")
    p_priv.add_argument("vault_root")

    p_idx = sub.add_parser("index")
    p_idx.add_argument("vault_root")

    p_dead = sub.add_parser("deadlinks")
    p_dead.add_argument("vault_root")

    p_mob = sub.add_parser("mobile")
    p_mob.add_argument("src_vault")
    p_mob.add_argument("dest_vault")

    args = parser.parse_args(argv)

    if args.cmd == "corruption":
        ok, messages = probe_corruption(args.dir)
    elif args.cmd == "privacy":
        ok, messages = probe_privacy(args.vault_root)
    elif args.cmd == "index":
        ok, messages = probe_index(args.vault_root)
    elif args.cmd == "deadlinks":
        ok, messages = probe_deadlinks(args.vault_root)
    else:
        ok, messages = probe_mobile(args.src_vault, args.dest_vault)

    for message in messages:
        print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
