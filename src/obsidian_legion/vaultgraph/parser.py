"""Deterministic note parsing + wikilink resolution for the R5 graph.

Identity of a note = its vault-relative path. We extract wikilinks, inline +
frontmatter tags, headings and a title — all AFTER stripping code blocks
(fenced and inline) from a working copy, while ``body`` keeps the original
text for FTS + embedding input. Frontmatter YAML is parsed leniently: a
malformed block yields ``{}`` and the body after the closing ``---`` is kept.
Only stdlib + PyYAML (a base dependency) are used, so this module is import-safe
in the live MCP server without the [vaultgraph] extra.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Fence markers are assembled from a single backtick at runtime so this source
# never contains a literal triple-backtick (keeps it copy-safe inside md fences).
_TICK = "`"
_FENCE = _TICK * 3
_FENCED = re.compile(re.escape(_FENCE) + r".*?" + re.escape(_FENCE), re.DOTALL)
_FENCED_TILDE = re.compile(r"~~~.*?~~~", re.DOTALL)
_INLINE = re.compile(_TICK + r"[^" + _TICK + r"\n]*" + _TICK)
_WIKILINK = re.compile(r"\[\[([^\[\]]+?)\]\]")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_TAG = re.compile(r"(?<![\w#])#([A-Za-z_][\w/-]*)")
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class RawLink:
    target: str
    alias: str | None
    heading: str | None


@dataclass
class ParsedNote:
    relpath: str
    title: str
    tags: list[str]
    links: list[RawLink]
    headings: list[str]
    body: str
    frontmatter: dict = field(default_factory=dict)


def canonical_key(name: str) -> str:
    """casefold + trim + collapse internal whitespace to a single space."""
    return _WS.sub(" ", name).strip().casefold()


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            block = "".join(lines[1:i])
            body = "".join(lines[i + 1:])
            try:
                data = yaml.safe_load(block)
            except Exception:
                data = None
            return (data if isinstance(data, dict) else {}), body
    return {}, text  # no closing delimiter → not frontmatter


def _strip_code(text: str) -> str:
    stripped = _FENCED.sub(" ", text)
    stripped = _FENCED_TILDE.sub(" ", stripped)
    return _INLINE.sub(" ", stripped)


def _parse_links(stripped: str) -> list[RawLink]:
    links: list[RawLink] = []
    for match in _WIKILINK.finditer(stripped):
        inner = match.group(1).strip()
        alias: str | None = None
        if "|" in inner:
            inner, alias_part = inner.split("|", 1)
            alias = alias_part.strip() or None
        heading: str | None = None
        if "#" in inner:
            inner, heading_part = inner.split("#", 1)
            heading = heading_part.strip() or None
        target = inner.strip()
        if not target:  # e.g. [[#Section]] — intra-note anchor, no target
            continue
        links.append(RawLink(target=target, alias=alias, heading=heading))
    return links


def _frontmatter_tags(frontmatter: dict) -> list[str]:
    raw = frontmatter.get("tags")
    if raw is None:
        raw = frontmatter.get("tag")
    out: list[str] = []
    if isinstance(raw, str):
        out = [tok for tok in re.split(r"[,\s]+", raw.strip()) if tok]
    elif isinstance(raw, (list, tuple)):
        out = [str(x).strip() for x in raw if str(x).strip()]
    return [t.lstrip("#") for t in out]


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def parse_note(vault_root: Path, relpath: Path) -> ParsedNote:
    rel = Path(relpath)
    text = (Path(vault_root) / rel).read_text(encoding="utf-8", errors="replace")
    frontmatter, body = _split_frontmatter(text)
    stripped = _strip_code(body)

    headings = [m.strip() for m in _HEADING.findall(stripped)]
    links = _parse_links(stripped)
    inline_tags = _TAG.findall(stripped)
    tags = _dedup(_frontmatter_tags(frontmatter) + inline_tags)

    ft = frontmatter.get("title")
    if ft is not None and str(ft).strip():
        title = str(ft).strip()
    elif headings:
        title = headings[0]
    else:
        title = rel.stem

    return ParsedNote(
        relpath=rel.as_posix(),
        title=title,
        tags=tags,
        links=links,
        headings=headings,
        body=body,
        frontmatter=frontmatter,
    )


class LinkResolver:
    """Resolves `[[wikilinks]]` against the index of NON-EXCLUDED notes only."""

    def __init__(self, note_relpaths: list[str]) -> None:
        self._path_index: dict[str, str] = {}
        self._stem_index: dict[str, list[str]] = {}
        for raw in note_relpaths:
            norm = raw.replace("\\", "/")
            self._path_index[norm] = norm
            if norm.endswith(".md"):
                self._path_index[norm[:-3]] = norm
            stem = Path(norm).stem
            self._stem_index.setdefault(stem.casefold(), []).append(norm)

    def resolve(self, target: str) -> str | None:
        cleaned = target.strip()
        if not cleaned:
            return None
        if "/" in cleaned or "\\" in cleaned:
            norm = cleaned.replace("\\", "/")
            if norm.startswith("./"):
                norm = norm[2:]
            return self._path_index.get(norm)
        stem = cleaned[:-3] if cleaned.lower().endswith(".md") else cleaned
        candidates = self._stem_index.get(stem.strip().casefold())
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        return sorted(candidates, key=lambda p: (p.count("/"), p))[0]
