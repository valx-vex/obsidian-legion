"""Layer 0: Graphify knowledge graph integration.

Wraps the graphify CLI (pip install graphifyy) as a subprocess.
Graphify turns any folder of code, docs, images, or videos into a
queryable knowledge graph using tree-sitter AST + LLM extraction.

This is an OPTIONAL layer. obsidian-legion works fine without it.
Install graphify separately: pip install graphifyy
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class GraphResult:
    """Result of a graphify build operation."""
    node_count: int = 0
    edge_count: int = 0
    community_count: int = 0
    output_dir: Path = field(default_factory=lambda: Path("."))
    graph_file: Optional[Path] = None
    success: bool = False
    error: Optional[str] = None


def is_available() -> bool:
    """Check if graphify CLI is installed and available."""
    return shutil.which("graphify") is not None


def build_graph(
    vault_root: Path,
    mode: str = "deep",
    update: bool = False,
    path: Optional[Path] = None,
) -> GraphResult:
    """Build knowledge graph from vault using graphify CLI.

    Args:
        vault_root: Root of the Obsidian vault
        mode: Extraction depth - "deep" (thorough) or "fast" (quick scan)
        update: Only process new/changed files (incremental)
        path: Specific path to scan (default: vault_root)

    Returns:
        GraphResult with node/edge counts and output location
    """
    if not is_available():
        return GraphResult(error="Graphify not installed. Install with: pip install graphifyy")

    scan_path = path or vault_root
    output_dir = vault_root / "graphify-out"

    cmd = ["graphify", str(scan_path), "--obsidian"]

    if mode == "deep":
        cmd.append("--mode")
        cmd.append("deep")

    if update:
        cmd.append("--update")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max for large vaults
            cwd=str(vault_root),
        )

        if result.returncode != 0:
            return GraphResult(
                error=f"Graphify failed (exit {result.returncode}): {result.stderr[:500]}",
                output_dir=output_dir,
            )

        # Parse graph.json if it exists
        graph_file = output_dir / "graph.json"
        if graph_file.exists():
            with open(graph_file) as f:
                graph_data = json.load(f)

            nodes = graph_data.get("nodes", [])
            edges = graph_data.get("edges", [])
            communities = set()
            for node in nodes:
                comm = node.get("community")
                if comm is None:
                    comm = node.get("group")
                if comm is not None:
                    communities.add(comm)

            return GraphResult(
                node_count=len(nodes),
                edge_count=len(edges),
                community_count=len(communities),
                output_dir=output_dir,
                graph_file=graph_file,
                success=True,
            )

        # graph.json not found but command succeeded
        return GraphResult(
            output_dir=output_dir,
            success=True,
            error="Graph built but graph.json not found in output",
        )

    except subprocess.TimeoutExpired:
        return GraphResult(error="Graphify timed out after 600s. Try --update for incremental builds.")
    except FileNotFoundError:
        return GraphResult(error="Graphify binary not found. Install with: pip install graphifyy")


def query_graph(question: str, vault_root: Path) -> str:
    """Query an existing knowledge graph.

    Args:
        question: Natural language question
        vault_root: Root of the Obsidian vault (where graphify-out/ lives)

    Returns:
        Answer string from graphify
    """
    if not is_available():
        return "Graphify not installed. Install with: pip install graphifyy"

    try:
        result = subprocess.run(
            ["graphify", "query", question],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(vault_root),
        )

        if result.returncode != 0:
            return f"Query failed: {result.stderr[:500]}"

        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        return "Query timed out after 120s."
    except FileNotFoundError:
        return "Graphify binary not found. Install with: pip install graphifyy"
