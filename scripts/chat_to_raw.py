#!/usr/bin/env python3
"""chat_to_raw.py -- Convert chat/conversation markdown files into raw/ format.

Scans a source directory (default: vault_root/09-archive/conversations/) for
.md files and writes slugified copies into vault_root/raw/ so the wiki
compiler can pick them up.

Output filenames follow the pattern:
    raw/chat-YYYY-MM-DD-<slug>.md

where YYYY-MM-DD comes from the source file's modification date and <slug>
is a filesystem-safe version of the original filename.

Usage:
    python scripts/chat_to_raw.py --vault-root /path/to/vault
    python scripts/chat_to_raw.py --vault-root /path/to/vault --source /other/dir
    python scripts/chat_to_raw.py --vault-root /path/to/vault --limit 5
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SOURCE_SUBDIR = "09-archive/conversations"
RAW_DIR = "raw"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def slugify(text: str, *, max_length: int = 80) -> str:
    """Convert *text* into a filesystem-safe slug.

    - Normalises unicode to ASCII where possible (e.g. accented chars).
    - Lowercases, strips non-alphanumeric characters (except hyphens).
    - Collapses consecutive hyphens.
    - Trims to *max_length* characters.
    """
    # Normalise unicode -> ASCII approximations.
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    # Lowercase and replace non-alnum with hyphens.
    text = re.sub(r"[^a-z0-9]+", "-", text.lower())
    # Strip leading/trailing hyphens and collapse multiples.
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:max_length]


def file_date_prefix(path: Path) -> str:
    """Return the file's mtime formatted as YYYY-MM-DD."""
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def build_output_name(source_path: Path) -> str:
    """Build a raw/ filename for a chat source file.

    Format: chat-YYYY-MM-DD-<slug>.md
    """
    stem = source_path.stem  # filename without extension
    date_prefix = file_date_prefix(source_path)
    slug = slugify(stem)
    if not slug:
        slug = "untitled"
    return f"chat-{date_prefix}-{slug}.md"


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------


def discover_sources(source_dir: Path) -> list[Path]:
    """Recursively find all .md files under *source_dir*."""
    results: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(source_dir):
        for fn in filenames:
            if fn.lower().endswith(".md"):
                results.append(Path(dirpath) / fn)
    results.sort()
    return results


# ---------------------------------------------------------------------------
# Main conversion logic
# ---------------------------------------------------------------------------


def convert(
    vault_root: Path,
    *,
    source: Path | None = None,
    limit: int | None = None,
) -> None:
    vault_root = vault_root.resolve()
    if not vault_root.is_dir():
        print(f"Error: vault root does not exist: {vault_root}", file=sys.stderr)
        sys.exit(1)

    source_dir = source if source is not None else vault_root / DEFAULT_SOURCE_SUBDIR
    source_dir = source_dir.resolve()

    raw_dir = vault_root / RAW_DIR

    print(f"Vault root : {vault_root}")
    print(f"Source dir : {source_dir}")
    print(f"Output dir : {raw_dir}")
    print()

    if not source_dir.is_dir():
        print(f"Error: source directory does not exist: {source_dir}", file=sys.stderr)
        sys.exit(1)

    # Ensure raw/ exists.
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Discover source files.
    all_sources = discover_sources(source_dir)
    total = len(all_sources)
    if limit is not None:
        all_sources = all_sources[:limit]
    process_count = len(all_sources)
    print(f"Found {total} .md files, processing {process_count}")

    converted = 0
    skipped = 0

    for filepath in all_sources:
        out_name = build_output_name(filepath)
        out_path = raw_dir / out_name

        # Skip if output already exists.
        if out_path.exists():
            skipped += 1
            continue

        try:
            content = filepath.read_text("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"  SKIP (read error) {filepath.name}: {exc}")
            skipped += 1
            continue

        out_path.write_text(content, "utf-8")
        converted += 1
        print(f"  -> {out_name}")

    print()
    print(f"Converted {converted} files, {skipped} skipped (already exist)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Convert chat/conversation markdown files into raw/ format "
            "for wiki compilation."
        ),
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        required=True,
        help="Root directory of the Obsidian vault.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help=(
            "Source directory containing chat .md files. "
            f"Default: vault_root/{DEFAULT_SOURCE_SUBDIR}"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N files (for testing).",
    )
    args = parser.parse_args()

    convert(
        vault_root=args.vault_root,
        source=args.source,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
