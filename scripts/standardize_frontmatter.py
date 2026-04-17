#!/usr/bin/env python3
"""Scan an Obsidian vault and standardize YAML frontmatter across all .md files.

For each markdown file:
  - If no frontmatter exists: add a minimal canonical template.
  - If frontmatter exists: add any missing canonical fields with defaults.

Existing values are NEVER overwritten — only missing fields are added.

Usage:
    python scripts/standardize_frontmatter.py --vault-root ~/my-vault --dry-run
    python scripts/standardize_frontmatter.py --vault-root ~/my-vault --limit 20
    python scripts/standardize_frontmatter.py --vault-root ~/my-vault --dir 01-consciousness
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml

# ── Directories to skip ────────────────────────────────────────────

EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        ".obsidian",
        ".git",
        "wiki",
        "wiki-public",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".smart-env",
        "raw",
    }
)

# ── Canonical fields (11 total) and their defaults ─────────────────

CANONICAL_FIELDS: tuple[str, ...] = (
    "title",
    "type",
    "status",
    "created",
    "updated",
    "aliases",
    "tags",
    "project",
    "area",
    "source",
    "publish",
    "related",
)

# Top-level directory prefix → type mapping
DIR_TYPE_MAP: dict[str, str] = {
    "00-inbox": "inbox",
    "01-consciousness": "research",
    "02-books": "source",
    "03-code": "project",
    "04-work": "operations",
    "05-vexnet": "project",
    "06-daily": "daily",
    "07-media": "source",
    "08-publishing": "writing",
    "09-archive": "archive",
    "99-vault": "operations",
}

# Type → default kind tag
TYPE_KIND_TAG: dict[str, str] = {
    "research": "kind/research",
    "source": "kind/source",
    "project": "kind/project",
    "operations": "kind/operations",
    "daily": "kind/daily",
    "writing": "kind/writing",
    "archive": "kind/archive",
    "inbox": "kind/inbox",
}

# ── Frontmatter parsing / serializing ──────────────────────────────

_FM_PATTERN = re.compile(r"\A---[ \t]*\n(.*?)---[ \t]*\n", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """Return (metadata_dict | None, body_after_frontmatter).

    Returns ``(None, full_text)`` when no valid frontmatter fence is found
    and ``({}, body)`` when fences exist but content is empty or invalid.
    """
    normalized = text.replace("\r\n", "\n")
    m = _FM_PATTERN.match(normalized)
    if m is None:
        return None, normalized
    raw_yaml = m.group(1)
    body = normalized[m.end():]
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError:
        return None, normalized  # treat malformed as "no frontmatter"
    if not isinstance(data, dict):
        data = {}
    return data, body


def serialize_frontmatter(metadata: dict[str, Any]) -> str:
    """Dump *metadata* to a ``---`` fenced YAML string."""
    dumped = yaml.safe_dump(
        metadata,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=120,
    ).rstrip()
    return f"---\n{dumped}\n---\n"


# ── Inference helpers ──────────────────────────────────────────────


def infer_type(rel_path: Path) -> str:
    """Derive a note *type* from its position inside the vault."""
    top = rel_path.parts[0] if rel_path.parts else ""
    return DIR_TYPE_MAP.get(top, "note")


def infer_project(rel_path: Path) -> str | None:
    """Best-effort project name from the directory hierarchy."""
    parts = rel_path.parts
    # Skip the first part (top-level area dir) and the filename
    if len(parts) >= 3:
        return parts[-2]  # immediate parent directory
    return None


def infer_area(rel_path: Path) -> str | None:
    """Top-level area directory (e.g. ``03-code``)."""
    if rel_path.parts:
        return rel_path.parts[0]
    return None


def title_from_filename(path: Path) -> str:
    """Derive a human-readable title from the filename stem."""
    stem = path.stem
    # Strip leading dates like 2025-04-16_ or 20250416_
    stem = re.sub(r"^\d{4}-?\d{2}-?\d{2}[_-]?", "", stem)
    # Replace separators with spaces
    stem = stem.replace("_", " ").replace("-", " ")
    return stem.strip() or path.stem


def mtime_iso(path: Path) -> str:
    """Return the file mtime as an ISO-8601 date string (YYYY-MM-DD)."""
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


# ── Core logic ─────────────────────────────────────────────────────


class FrontmatterResult:
    """Container for a single file's processing outcome."""

    __slots__ = ("path", "status", "added_fields", "error")

    def __init__(
        self,
        path: Path,
        status: str,
        added_fields: list[str] | None = None,
        error: str | None = None,
    ):
        self.path = path
        self.status = status  # "complete" | "updated" | "created" | "skipped" | "error"
        self.added_fields = added_fields or []
        self.error = error


def build_defaults(path: Path, rel_path: Path) -> dict[str, Any]:
    """Build a full dict of canonical defaults for *path*."""
    note_type = infer_type(rel_path)
    status = "archive" if note_type == "archive" else "active"
    kind_tag = TYPE_KIND_TAG.get(note_type)
    default_tags: list[str] = [kind_tag] if kind_tag else []
    file_date = mtime_iso(path)

    return {
        "title": title_from_filename(path),
        "type": note_type,
        "status": status,
        "created": file_date,
        "updated": file_date,
        "aliases": [],
        "tags": default_tags,
        "project": infer_project(rel_path),
        "area": infer_area(rel_path),
        "source": None,
        "publish": False,
        "related": [],
    }


def process_file(
    path: Path,
    vault_root: Path,
    *,
    dry_run: bool = False,
) -> FrontmatterResult:
    """Process a single markdown file. Returns a result describing what changed."""
    rel_path = path.relative_to(vault_root)

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return FrontmatterResult(path, "error", error=str(exc))

    defaults = build_defaults(path, rel_path)
    existing, body = parse_frontmatter(text)

    if existing is None:
        # No frontmatter at all — create full template
        if dry_run:
            return FrontmatterResult(path, "created", added_fields=list(CANONICAL_FIELDS))

        new_text = serialize_frontmatter(defaults) + body
        path.write_text(new_text, encoding="utf-8")
        return FrontmatterResult(path, "created", added_fields=list(CANONICAL_FIELDS))

    # Frontmatter exists — fill in missing canonical fields only
    added: list[str] = []
    merged = dict(existing)  # preserve insertion order
    for field in CANONICAL_FIELDS:
        if field not in merged:
            merged[field] = defaults[field]
            added.append(field)

    if not added:
        return FrontmatterResult(path, "complete")

    if dry_run:
        return FrontmatterResult(path, "updated", added_fields=added)

    # Rebuild file: reordered frontmatter (canonical first, extras after) + body
    ordered: dict[str, Any] = {}
    for field in CANONICAL_FIELDS:
        if field in merged:
            ordered[field] = merged[field]
    for key, value in merged.items():
        if key not in ordered:
            ordered[key] = value

    new_text = serialize_frontmatter(ordered) + body
    path.write_text(new_text, encoding="utf-8")
    return FrontmatterResult(path, "updated", added_fields=added)


def walk_vault(vault_root: Path, subdir: str | None = None) -> list[Path]:
    """Collect all .md files in the vault, respecting EXCLUDED_DIRS."""
    start = vault_root / subdir if subdir else vault_root
    if not start.is_dir():
        raise FileNotFoundError(f"Directory not found: {start}")

    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(start):
        # Prune excluded directories in-place so os.walk skips them
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for fname in sorted(filenames):
            if fname.endswith(".md"):
                results.append(Path(dirpath) / fname)
    return results


def run(
    vault_root: Path,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    subdir: str | None = None,
) -> list[FrontmatterResult]:
    """Walk the vault and standardize frontmatter. Returns per-file results."""
    files = walk_vault(vault_root, subdir)
    if limit is not None:
        files = files[:limit]

    return [process_file(f, vault_root, dry_run=dry_run) for f in files]


def print_report(results: list[FrontmatterResult], *, dry_run: bool = False) -> None:
    """Print a human-readable summary to stdout."""
    complete = [r for r in results if r.status == "complete"]
    updated = [r for r in results if r.status == "updated"]
    created = [r for r in results if r.status == "created"]
    errors = [r for r in results if r.status == "error"]

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"\n[{mode}] Scanned {len(results)} files:")
    print(f"  - {len(complete)} already have complete frontmatter")
    print(f"  - {len(updated)} missing some fields ({'would add' if dry_run else 'added'} defaults)")
    print(f"  - {len(created)} have no frontmatter at all ({'would add' if dry_run else 'added'} full template)")
    if errors:
        print(f"  - {len(errors)} errors:")
        for r in errors:
            print(f"      {r.path}: {r.error}")
    print()


# ── CLI ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Standardize YAML frontmatter across an Obsidian vault.",
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        required=True,
        help="Root directory of the Obsidian vault.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without modifying files.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N files.",
    )
    parser.add_argument(
        "--dir",
        dest="subdir",
        default=None,
        help="Only process files under this subdirectory.",
    )
    args = parser.parse_args(argv)
    vault_root = args.vault_root.expanduser().resolve()

    if not vault_root.is_dir():
        print(f"Error: {vault_root} is not a directory.", file=sys.stderr)
        return 1

    results = run(vault_root, dry_run=args.dry_run, limit=args.limit, subdir=args.subdir)
    print_report(results, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
