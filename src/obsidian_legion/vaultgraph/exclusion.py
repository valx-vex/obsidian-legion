"""Component-wise vault exclusion for the R5 semantic-vault graph.

Pure stdlib — no heavy deps — so the live MCP server imports it freely.
A note is excluded iff ANY segment of its vault-relative path is a reserved
name (EXCLUDED_SEGMENTS + user extras), the top-level wiki output dir, or a
virtualenv interior (a ``site-packages`` segment, or any ancestor dir holding
a ``pyvenv.cfg``). Exclusion is depth-independent: ``.murphy_private`` is
caught at ``a/b/.murphy_private/x.md`` exactly as at the vault root.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

EXCLUDED_SEGMENTS = frozenset({
    ".murphy_private", ".obsidian", ".git", ".github", ".legion",
    ".trash", "node_modules", "__pycache__", ".venv", ".crystl", ".claude",
})
HARD_PRIVATE_SEGMENT = ".murphy_private"


class ExclusionEngine:
    """Decides which vault notes R5 is allowed to see."""

    def __init__(self, vault_root: Path, extra_segments: frozenset[str] = frozenset(),
                 wiki_dirname: str = "wiki") -> None:
        self.vault_root = Path(vault_root)
        self.extra_segments = frozenset(extra_segments)
        self.wiki_dirname = wiki_dirname
        self._segments = EXCLUDED_SEGMENTS | self.extra_segments

    def is_excluded(self, relpath: Path | str) -> bool:
        rel = Path(relpath)
        parts = rel.parts
        if not parts:
            return False
        # 1. reserved segment anywhere (component-wise, any depth)
        if any(part in self._segments for part in parts):
            return True
        # 2. wiki output dir — top level only (a deeper "wiki/" is real content)
        if parts[0] == self.wiki_dirname:
            return True
        # 3. virtualenv heuristic
        if "site-packages" in parts:
            return True
        for parent in rel.parents:
            if parent == Path("."):
                continue
            if (self.vault_root / parent / "pyvenv.cfg").exists():
                return True
        return False

    def is_hard_private(self, relpath: Path | str) -> bool:
        return HARD_PRIVATE_SEGMENT in Path(relpath).parts

    def _dir_excluded(self, rel_child: Path, abs_child: Path) -> bool:
        name = rel_child.name
        if name in self._segments or name == "site-packages":
            return True
        if len(rel_child.parts) == 1 and name == self.wiki_dirname:
            return True
        if (abs_child / "pyvenv.cfg").exists():
            return True
        return False

    def iter_notes(self) -> Iterator[Path]:
        matches: list[Path] = []
        root = self.vault_root
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = Path(dirpath).relative_to(root)
            kept: list[str] = []
            for name in dirnames:
                rel_child = (rel_dir / name) if rel_dir != Path(".") else Path(name)
                if self._dir_excluded(rel_child, Path(dirpath) / name):
                    continue
                kept.append(name)
            dirnames[:] = kept  # prune in place — never descend into excluded dirs
            for fname in filenames:
                if not fname.endswith(".md"):
                    continue
                rel = (rel_dir / fname) if rel_dir != Path(".") else Path(fname)
                if self.is_excluded(rel):
                    continue
                matches.append(rel)
        matches.sort()
        return iter(matches)
