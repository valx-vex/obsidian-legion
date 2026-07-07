from __future__ import annotations

import argparse
from pathlib import Path

from .config import LegionPaths
from .store import TaskStore


def _resolve_vault(vault: str | None) -> Path:
    from .vaultgraph import registry as reg

    if vault is None:
        _name, root = reg.default_vault()
        return Path(root)
    candidate = Path(vault).expanduser()
    if candidate.exists() and candidate.is_dir():
        return candidate.resolve()
    registry = reg.load_registry()
    if vault in registry:
        return Path(registry[vault])
    return candidate.resolve()


def _graph_db(root: Path):
    from .vaultgraph.graphdb import GraphDB

    db_path = root / ".legion" / "graph.sqlite"
    if not db_path.exists():
        return None
    return GraphDB(db_path)


def _graph_embedder(root: Path):
    from .vaultgraph.embedder import VaultEmbedder

    return VaultEmbedder()


def _open_graph(vault: str | None):
    """Returns (root, db, error_payload). On success error_payload is None."""
    try:
        root = _resolve_vault(vault)
        db = _graph_db(root)
    except ImportError:
        return None, None, {"error": "vaultgraph extras not installed"}
    except FileNotFoundError:
        return None, None, {"error": "graph not built yet",
                            "hint": "obsidian-legion graph build"}
    if db is None:
        return None, None, {"error": "graph not built yet",
                            "hint": "obsidian-legion graph build"}
    return root, db, None


def _hit_key(hit: dict):
    return hit.get("path") or hit.get("relpath") or hit.get("id")


def _hit_score(hit: dict) -> float:
    for key in ("score", "cosine", "weight"):
        value = hit.get(key)
        if value is not None:
            return float(value)
    return 0.0


def _merge_hits(lexical: list[dict], semantic: list[dict]) -> list[dict]:
    best: dict = {}
    for source, hits in (("lexical", lexical), ("semantic", semantic)):
        for hit in hits or []:
            key = _hit_key(hit)
            if key is None:
                continue
            score = _hit_score(hit)
            entry = best.get(key)
            if entry is None:
                best[key] = {"path": key, "score": score, "sources": [source], "raw": hit}
            else:
                entry["sources"].append(source)
                if score > entry["score"]:
                    entry["score"] = score
    merged = list(best.values())
    merged.sort(key=lambda item: (-item["score"], item["path"]))
    return merged


def _read_wiki_page(root: Path, name: str) -> dict:
    wiki = root / "wiki"
    candidates = [
        wiki / name, wiki / f"{name}.md",
        wiki / "topics" / name, wiki / "topics" / f"{name}.md",
        wiki / "entities" / name, wiki / "entities" / f"{name}.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return {"name": name,
                    "path": str(candidate.relative_to(root)),
                    "content": candidate.read_text(encoding="utf-8")}
    return {"error": "page not found",
            "hint": "obsidian-legion wiki compile", "name": name}


def build_mcp(paths: LegionPaths):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise SystemExit(
            "The optional 'mcp' dependency is not installed. Install with `pip install .[mcp]`."
        ) from exc

    store = TaskStore(paths)
    mcp = FastMCP("obsidian-legion")

    @mcp.tool()
    def capture_task(
        title: str,
        summary: str,
        project: str = "general",
        area: str = "general",
        assignee: str = "unassigned",
        priority: str = "P2",
        created_by: str = "agent",
    ) -> dict:
        task = store.capture(
            title,
            summary=summary,
            project=project,
            area=area,
            assignee=assignee,
            priority=priority,
            created_by=created_by,
        )
        return task.to_dict()

    @mcp.tool()
    def list_tasks(
        status: str | None = None,
        assignee: str | None = None,
        project: str | None = None,
        include_done: bool = False,
    ) -> list[dict]:
        statuses = [status] if status else None
        return [
            task.to_dict()
            for task in store.list_tasks(
                statuses=statuses,
                assignee=assignee,
                project=project,
                include_done=include_done,
            )
        ]

    @mcp.tool()
    def next_tasks(assignee: str | None = None, limit: int = 10) -> list[dict]:
        return [task.to_dict() for task in store.next_tasks(assignee=assignee, limit=limit)]

    @mcp.tool()
    def claim_task(task_id: str, assignee: str, status: str = "in_progress") -> dict:
        return store.claim_task(task_id, assignee, status=status).to_dict()

    @mcp.tool()
    def complete_task(task_id: str, note: str | None = None) -> dict:
        return store.complete_task(task_id, note=note).to_dict()

    @mcp.tool()
    def refresh_dashboards() -> list[str]:
        return [str(path) for path in store.refresh()]

    # --- Wiki tools (Karpathy LLM Wiki pattern) ---

    from .wiki_store import WikiStore

    wiki = WikiStore(paths)

    @mcp.tool()
    def wiki_bootstrap() -> dict:
        """Create wiki/ and raw/ directories with seed files."""
        created = wiki.bootstrap()
        return {"created": [str(p) for p in created]}

    @mcp.tool()
    def wiki_ingest(raw_path: str) -> dict:
        """Ingest a raw file into the wiki via LLM compilation."""
        articles = wiki.ingest(Path(raw_path).expanduser().resolve())
        return {"articles": [a.to_dict() for a in articles]}

    @mcp.tool()
    def wiki_compile() -> dict:
        """Compile all new/changed raw files into wiki articles."""
        articles = wiki.compile_all()
        return {
            "compiled": len(articles),
            "articles": [a.to_dict() for a in articles],
        }

    @mcp.tool()
    def wiki_compile_vault(dry_run: bool = False) -> dict:
        """Compile all new/changed .md files across the entire vault into wiki articles.

        Scans the full vault (excluding wiki/, .obsidian/, .git/, node_modules/, .venv/, __pycache__/).
        Uses manifest tracking to skip already-ingested files and detect changes by hash.
        """
        articles = wiki.compile_vault(dry_run=dry_run)
        return {
            "compiled": len(articles),
            "articles": [a.to_dict() for a in articles],
        }

    @mcp.tool()
    def wiki_compile_public(dry_run: bool = False) -> dict:
        """Compile non-ignored files into public wiki."""
        articles = wiki.compile_public(dry_run=dry_run)
        return {"compiled": len(articles), "articles": [a.to_dict() for a in articles]}

    @mcp.tool()
    def wiki_export(output_dir: str) -> dict:
        """Export public wiki to external directory."""
        exported = wiki.export_public(Path(output_dir))
        return {"exported": [str(p) for p in exported]}

    @mcp.tool()
    def wiki_search(query: str, limit: int = 10, deep: bool = False) -> list[dict]:
        """Search the wiki for articles matching a query.

        When deep=True, falls back to Qdrant vector search if text search returns fewer than `limit` results.
        """
        return [a.to_dict() for a in wiki.search(query, limit=limit, deep=deep)]

    @mcp.tool()
    def wiki_status() -> dict:
        """Show wiki compilation status: counts, pending files, paths."""
        return wiki.status()

    @mcp.tool()
    def wiki_list(article_type: str = "") -> list[dict]:
        """List all wiki articles, optionally filtered by type (entity/topic/source)."""
        atype = article_type if article_type else None
        return [a.to_dict() for a in wiki.list_articles(article_type=atype)]

    # --- Layer 0: Graphify tools ---

    @mcp.tool()
    def graphify_build(mode: str = "deep", update: bool = True) -> dict:
        """Layer 0: Build knowledge graph from vault using Graphify.

        Requires graphifyy package (pip install graphifyy).
        Turns code, docs, images, videos into a queryable knowledge graph.
        """
        from .graphify import is_available, build_graph

        if not is_available():
            return {"error": "Graphify not installed. Run: pip install graphifyy"}
        result = build_graph(paths.vault_root, mode=mode, update=update)
        if result.error and not result.success:
            return {"error": result.error}
        return {
            "nodes": result.node_count,
            "edges": result.edge_count,
            "communities": result.community_count,
            "output": str(result.output_dir),
            "success": result.success,
        }

    @mcp.tool()
    def graphify_query(question: str) -> dict:
        """Query the knowledge graph built by Graphify.

        First run graphify_build to create the graph, then query it.
        """
        from .graphify import is_available, query_graph

        if not is_available():
            return {"error": "Graphify not installed. Run: pip install graphifyy"}
        answer = query_graph(question, paths.vault_root)
        return {"answer": answer}

    # --- Layer 3: vault graph tools (VEXPEDIA) — all heavy imports lazy ---

    @mcp.tool()
    def vault_search(query: str, k: int = 8, include_absent: bool = False,
                     vault: str | None = None) -> dict:
        """Hybrid FTS5 + semantic search over the vault graph. Absent-masked by default."""
        root, db, error = _open_graph(vault)
        if error:
            return error
        lexical = db.search_lexical(query, k=k, include_absent=include_absent)
        semantic: list[dict] = []
        try:
            semantic = _graph_embedder(root).search(query, k=k, include_absent=include_absent)
        except Exception:
            semantic = []
        return {"results": _merge_hits(lexical, semantic)[:k]}

    @mcp.tool()
    def vault_neighbors(key: str, depth: int = 1, kinds: list[str] | None = None,
                        vault: str | None = None) -> dict:
        """Typed neighborhood of a note/entity in the vault graph."""
        _root, db, error = _open_graph(vault)
        if error:
            return error
        return db.neighbors(key, depth=depth, kinds=kinds)

    @mcp.tool()
    def vault_path(a: str, b: str, vault: str | None = None) -> dict:
        """Shortest path between two nodes in the vault graph."""
        _root, db, error = _open_graph(vault)
        if error:
            return error
        return {"path": db.shortest_path(a, b)}

    @mcp.tool()
    def vault_communities(query: str | None = None, vault: str | None = None) -> dict:
        """List graph communities, optionally filtered by a substring of the name."""
        _root, db, error = _open_graph(vault)
        if error:
            return error
        communities = db.communities()
        if query:
            needle = query.lower()
            communities = [c for c in communities
                           if needle in str(c.get("name", "")).lower()]
        return {"communities": communities}

    @mcp.tool()
    def vault_page(name: str, vault: str | None = None) -> dict:
        """Fetch a compiled VEXPEDIA wiki page by name."""
        root, _db, error = _open_graph(vault)
        if error:
            return error
        return _read_wiki_page(root, name)

    @mcp.tool()
    def vault_stats(vault: str | None = None) -> dict:
        """Graph size/coverage stats."""
        _root, db, error = _open_graph(vault)
        if error:
            return error
        return db.stats()

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Obsidian Legion MCP server.")
    parser.add_argument("--vault-root", type=Path, help="Absolute path to the vault root.")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http"])
    args = parser.parse_args(argv)

    paths = LegionPaths.discover(args.vault_root)
    mcp = build_mcp(paths)
    mcp.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
