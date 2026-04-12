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
