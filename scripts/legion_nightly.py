#!/usr/bin/env python3
"""Legion nightly job (R5 §4.6): graph update THEN wiki update, one report.

Run by launchd (com.vex.legion.nightly, 05:15) under the repo .venv. Resolves
the vault from the registry (or a bare path), runs GraphBuilder.update, then —
unless --skip-wiki — preflights the provider chain and runs WikiWriter.update
(all providers down => graph-only night, noted in the report). Exit 0 unless
the GRAPH build itself failed; a wiki/provider failure is reported, not fatal.

Heavy deps (networkx/numpy/scipy/qdrant/sentence-transformers) are imported
lazily inside GraphBuilder/WikiWriter, never here at module top.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path


def _resolve_vault(vault_arg):
    from obsidian_legion.vaultgraph import registry
    if not vault_arg:
        return registry.default_vault()
    roots = registry.load_registry()
    if vault_arg in roots:
        return vault_arg, roots[vault_arg]
    candidate = Path(vault_arg).expanduser()
    if candidate.exists():
        return candidate.name, candidate.resolve()
    raise SystemExit(f"unknown vault (not in registry, not a path): {vault_arg}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Legion nightly graph + wiki job")
    parser.add_argument("--vault", default="", help="registry name or absolute path")
    parser.add_argument("--skip-wiki", action="store_true")
    parser.add_argument("--budget", type=int, default=25)
    args = parser.parse_args(argv)

    from obsidian_legion.vaultgraph import report
    from obsidian_legion.vaultgraph.builder import GraphBuilder

    vault_name, vault_root = _resolve_vault(args.vault)

    graph_ok = True
    try:
        graph_report = GraphBuilder(vault_root).update()
        if graph_report.get("error"):
            graph_ok = False
    except Exception as exc:
        traceback.print_exc()
        graph_report = {"error": f"{type(exc).__name__}: {exc}"}
        graph_ok = False

    wiki_report = None
    if not args.skip_wiki and graph_ok:
        try:
            from obsidian_legion.vaultgraph.graphdb import GraphDB
            from obsidian_legion.vaultgraph.providers import (
                ProviderChain, default_providers)
            from obsidian_legion.vaultgraph.wiki_writer import WikiWriter

            chain = ProviderChain(default_providers())
            if any(chain.preflight().values()):
                db = GraphDB(vault_root / ".legion" / "graph.sqlite")
                wiki_report = WikiWriter(vault_root, db, chain).update(budget=args.budget)
            else:
                wiki_report = {"skipped": "all providers down"}
        except Exception as exc:
            traceback.print_exc()
            wiki_report = {"skipped": f"error — {type(exc).__name__}: {exc}"}
    elif args.skip_wiki:
        wiki_report = {"skipped": "--skip-wiki"}

    report_path = report.write_report(vault_name, graph_report, wiki_report)
    print(json.dumps({
        "vault": vault_name,
        "graph_ok": graph_ok,
        "report": str(report_path),
        "graph": graph_report,
        "wiki": wiki_report,
    }, indent=2, default=str))
    return 0 if graph_ok else 1


if __name__ == "__main__":
    sys.exit(main())
