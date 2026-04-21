from __future__ import annotations

import argparse
from pathlib import Path

from .config import LegionPaths
from .store import TaskStore


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
