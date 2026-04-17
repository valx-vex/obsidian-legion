#!/usr/bin/env python3
"""Watch vault for new/changed .md files and auto-compile wiki articles.

Polls the vault at a configurable interval (default 30s), detects new or
modified .md files via mtime comparison, and invokes the obsidian-legion
wiki ingest command for each changed file.

No external dependencies required -- uses only the stdlib.

Usage:
    python scripts/wiki_watch.py --vault-root ~/my-vault
    python scripts/wiki_watch.py --vault-root ~/my-vault --model llama3.2:3b --tier light
    python scripts/wiki_watch.py --vault-root ~/my-vault --interval 60
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXCLUDE_DIRS: set[str] = {
    "wiki",
    ".obsidian",
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    ".smart-env",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    """Return current time formatted as [HH:MM:SS]."""
    return datetime.now().strftime("[%H:%M:%S]")


def _scan_vault(vault_root: Path) -> dict[str, float]:
    """Walk *vault_root* for .md files, returning {path_str: mtime}."""
    results: dict[str, float] = {}
    for dirpath, dirnames, filenames in os.walk(vault_root):
        # Prune excluded directories in-place so os.walk skips them.
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.lower().endswith(".md"):
                full = os.path.join(dirpath, fn)
                try:
                    results[full] = os.stat(full).st_mtime
                except OSError:
                    pass
    return results


def _build_ingest_cmd(
    file_path: str,
    vault_root: str,
    model: str | None,
    tier: str | None,
) -> list[str]:
    """Build the obsidian-legion wiki ingest command."""
    cmd = ["obsidian-legion", "wiki", "ingest", file_path, "--vault-root", vault_root]
    if model:
        cmd.extend(["--model", model])
    # Note: the CLI doesn't expose --tier on ingest directly; the compiler
    # picks tier from config. We pass --model which is the primary control.
    return cmd


# ---------------------------------------------------------------------------
# Main watch loop
# ---------------------------------------------------------------------------


def watch(
    vault_root: Path,
    *,
    model: str | None = None,
    tier: str | None = None,
    interval: int = 30,
) -> None:
    vault_root = vault_root.expanduser().resolve()
    if not vault_root.is_dir():
        print(f"Error: vault root does not exist: {vault_root}", file=sys.stderr)
        sys.exit(1)

    print(f"Vault root : {vault_root}")
    print(f"Model      : {model or '(default)'}")
    print(f"Tier       : {tier or '(default)'}")
    print(f"Interval   : {interval}s")
    print()
    print(f"{_timestamp()} Initial scan...")

    # Build initial mtime snapshot.
    known: dict[str, float] = _scan_vault(vault_root)
    total_compiled = 0
    total_articles = 0

    print(f"{_timestamp()} Tracking {len(known)} .md files. Watching for changes...")
    print()

    try:
        while True:
            time.sleep(interval)

            current = _scan_vault(vault_root)
            changed: list[str] = []

            for path, mtime in current.items():
                prev_mtime = known.get(path)
                if prev_mtime is None or mtime > prev_mtime:
                    changed.append(path)

            if not changed:
                continue

            for file_path in sorted(changed):
                rel = os.path.relpath(file_path, vault_root)
                cmd = _build_ingest_cmd(
                    file_path, str(vault_root), model, tier
                )
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=600,
                    )
                    if result.returncode == 0:
                        # Parse article count from output like "Ingested N article(s):"
                        output = result.stdout.strip()
                        n_articles = 0
                        for line in output.splitlines():
                            if "Ingested" in line and "article" in line:
                                try:
                                    n_articles = int(line.split()[1])
                                except (IndexError, ValueError):
                                    n_articles = 1
                            elif "Already up to date" in line:
                                n_articles = 0
                        if n_articles > 0:
                            total_compiled += 1
                            total_articles += n_articles
                            print(
                                f"{_timestamp()} Compiled: {rel} -> {n_articles} article(s)"
                            )
                        else:
                            print(f"{_timestamp()} Skipped (up to date): {rel}")
                    else:
                        print(
                            f"{_timestamp()} Error compiling {rel}: {result.stderr.strip()}"
                        )
                except subprocess.TimeoutExpired:
                    print(f"{_timestamp()} Timeout compiling {rel}")
                except FileNotFoundError:
                    print(
                        f"{_timestamp()} Error: 'obsidian-legion' command not found. "
                        "Is the package installed?",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            # Update known state after processing.
            known = current

    except KeyboardInterrupt:
        print()
        print(f"{_timestamp()} Watcher stopped.")
        print(f"  Files compiled : {total_compiled}")
        print(f"  Articles total : {total_articles}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Watch vault for .md changes and auto-compile wiki articles.",
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        required=True,
        help="Root directory of the Obsidian vault.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model to use for compilation.",
    )
    parser.add_argument(
        "--tier",
        choices=["heavy", "light"],
        default=None,
        help="Compilation tier (heavy=detailed, light=fast).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Poll interval in seconds (default: 30).",
    )
    args = parser.parse_args()

    watch(
        vault_root=args.vault_root,
        model=args.model,
        tier=args.tier,
        interval=args.interval,
    )


if __name__ == "__main__":
    main()
