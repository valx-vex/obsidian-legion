#!/usr/bin/env python3
"""Generate wiki articles in bulk, optionally with cloud models.

Imports the obsidian-legion library directly (no subprocess overhead),
supports --limit for partial runs, --dry-run for preview, and --vault-wide
to scan the entire vault instead of just raw/.

Usage:
    python scripts/wiki_generate.py --vault-root ~/my-vault --limit 10
    python scripts/wiki_generate.py --vault-root ~/my-vault --model qwen3.5:397b-cloud --vault-wide
    nohup python scripts/wiki_generate.py --vault-root ~/my-vault --vault-wide &
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Add src/ to the module search path so we can import obsidian_legion
# when running the script directly (without pip install -e).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from obsidian_legion.config import LegionPaths
from obsidian_legion.wiki_compiler import WikiCompiler
from obsidian_legion.wiki_store import WikiStore


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bulk wiki generation with progress reporting.",
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        required=True,
        help="Root directory of the Obsidian vault.",
    )
    parser.add_argument(
        "--model",
        default="llama3.2:3b",
        help="LLM model to use (default: llama3.2:3b).",
    )
    parser.add_argument(
        "--provider",
        choices=["ollama", "claude"],
        default="ollama",
        help="LLM provider (default: ollama).",
    )
    parser.add_argument(
        "--tier",
        choices=["heavy", "light"],
        default="heavy",
        help="Compilation tier: heavy=detailed, light=fast (default: heavy).",
    )
    parser.add_argument(
        "--vault-wide",
        action="store_true",
        help="Scan entire vault instead of just raw/.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N pending files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be compiled without doing it.",
    )
    args = parser.parse_args()

    paths = LegionPaths.discover(args.vault_root)
    compiler = WikiCompiler(
        provider=args.provider,
        model=args.model,
        tier=args.tier,
    )
    wiki = WikiStore(paths, compiler=compiler)
    wiki.bootstrap()

    if args.dry_run:
        print(f"Vault root : {paths.vault_root}")
        print(f"Model      : {args.model}")
        print(f"Provider   : {args.provider}")
        print(f"Tier       : {args.tier}")
        print(f"Mode       : {'vault-wide' if args.vault_wide else 'raw/ only'}")
        print(f"Limit      : {args.limit or 'none'}")
        print()

    # Use the library's compile methods which handle manifest tracking.
    # To support --limit, we do the pending-file discovery ourselves and
    # ingest one at a time so we can cap and report progress.
    from obsidian_legion.wiki_models import WikiManifest

    manifest = WikiManifest.load(paths.wiki_manifest)

    if args.vault_wide:
        pending = wiki._find_vault_pending(manifest)
    else:
        pending = wiki._find_pending(manifest)

    if args.limit is not None:
        pending = pending[: args.limit]

    if args.dry_run:
        print(f"Pending files: {len(pending)}")
        for p in pending:
            print(f"  {p}")
        return 0

    if not pending:
        print("Nothing to compile -- all files are up to date.")
        return 0

    print(f"Compiling {len(pending)} file(s) with {args.model} ({args.tier} tier)...")
    print()

    start = time.time()
    all_articles = []

    for idx, raw_path in enumerate(pending, start=1):
        file_start = time.time()
        try:
            articles = wiki.ingest(raw_path)
        except Exception as exc:
            print(f"  [{idx}/{len(pending)}] ERROR {raw_path.name}: {exc}")
            continue

        file_elapsed = time.time() - file_start
        all_articles.extend(articles)

        if articles:
            print(
                f"  [{idx}/{len(pending)}] {raw_path.name} "
                f"-> {len(articles)} article(s) ({file_elapsed:.1f}s)"
            )
        else:
            print(f"  [{idx}/{len(pending)}] {raw_path.name} (up to date)")

    elapsed = time.time() - start
    print()
    print(f"Generated {len(all_articles)} article(s) in {elapsed:.1f}s")
    if all_articles:
        print(f"Model: {args.model} | Provider: {args.provider} | Tier: {args.tier}")
        for a in all_articles[:20]:
            print(f"  {a.article_id} ({a.article_type})")
        if len(all_articles) > 20:
            print(f"  ... and {len(all_articles) - 20} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
