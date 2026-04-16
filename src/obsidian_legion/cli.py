from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .config import LegionPaths
from .store import TaskStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vault-native task engine for the Obsidian legion.")
    parser.add_argument("--vault-root", type=Path, help="Absolute path to the vault root.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("bootstrap", help="Create required task-system directories and state files.")

    capture = subparsers.add_parser("capture", help="Create a canonical task note.")
    capture.add_argument("title")
    capture.add_argument("--summary", required=True)
    capture.add_argument("--status", default="inbox")
    capture.add_argument("--priority", default="P2")
    capture.add_argument("--assignee", default="unassigned")
    capture.add_argument("--created-by", default="human")
    capture.add_argument("--project", default="general")
    capture.add_argument("--area", default="general")
    capture.add_argument("--lane", default="backlog")
    capture.add_argument("--effort", default="m")
    capture.add_argument("--due")
    capture.add_argument("--scheduled")
    capture.add_argument("--source-note")
    capture.add_argument("--tag", action="append", default=[])
    capture.add_argument("--blocker", action="append", default=[])
    capture.add_argument("--accept", action="append", default=[])
    capture.add_argument("--refresh", action="store_true")

    listing = subparsers.add_parser("list", help="List canonical tasks.")
    listing.add_argument("--status", action="append", default=[])
    listing.add_argument("--assignee")
    listing.add_argument("--project")
    listing.add_argument("--include-done", action="store_true")
    listing.add_argument("--format", choices=["table", "json", "ids"], default="table")

    next_parser = subparsers.add_parser("next", help="Show the best next tasks for an assignee.")
    next_parser.add_argument("--assignee")
    next_parser.add_argument("--limit", type=int, default=10)
    next_parser.add_argument("--format", choices=["table", "json", "ids"], default="table")

    claim = subparsers.add_parser("claim", help="Assign and claim a task.")
    claim.add_argument("task_id")
    claim.add_argument("--assignee", required=True)
    claim.add_argument("--status", default="in_progress")
    claim.add_argument("--refresh", action="store_true")

    update = subparsers.add_parser("update", help="Update task metadata.")
    update.add_argument("task_id")
    update.add_argument("--status")
    update.add_argument("--priority")
    update.add_argument("--assignee")
    update.add_argument("--project")
    update.add_argument("--area")
    update.add_argument("--lane")
    update.add_argument("--effort")
    update.add_argument("--due")
    update.add_argument("--clear-due", action="store_true")
    update.add_argument("--scheduled")
    update.add_argument("--clear-scheduled", action="store_true")
    update.add_argument("--summary")
    update.add_argument("--source-note")
    update.add_argument("--clear-source-note", action="store_true")
    update.add_argument("--add-tag", action="append", default=[])
    update.add_argument("--add-blocker", action="append", default=[])
    update.add_argument("--accept", action="append", default=[])
    update.add_argument("--log-note")
    update.add_argument("--refresh", action="store_true")

    done = subparsers.add_parser("done", help="Mark a task done.")
    done.add_argument("task_id")
    done.add_argument("--note")
    done.add_argument("--refresh", action="store_true")

    subparsers.add_parser("refresh", help="Rebuild dashboards and human rollups.")
    subparsers.add_parser("doctor", help="Show task-system health and detected paths.")

    wiki = subparsers.add_parser("wiki", help="LLM Wiki commands (Karpathy pattern).")
    wiki_sub = wiki.add_subparsers(dest="wiki_command", required=True)

    wiki_sub.add_parser("bootstrap", help="Create wiki/ and raw/ directories with seed files.")

    wiki_ingest = wiki_sub.add_parser("ingest", help="Ingest a raw file into the wiki.")
    wiki_ingest.add_argument("path", type=Path, help="Path to raw file.")

    wiki_compile = wiki_sub.add_parser("compile", help="Compile all new/changed raw files.")
    wiki_compile.add_argument("--dry-run", action="store_true", help="Show what would be compiled.")
    wiki_compile.add_argument("--vault-wide", action="store_true", help="Scan entire vault instead of just raw/.")
    wiki_compile.add_argument("--tier", choices=["heavy", "light"], default=None, help="Compilation tier (heavy=detailed, light=fast).")

    wiki_search = wiki_sub.add_parser("search", help="Search wiki articles.")
    wiki_search.add_argument("query", help="Search query.")
    wiki_search.add_argument("--limit", type=int, default=10)
    wiki_search.add_argument("--deep", action="store_true", help="Enable deep vector search via Qdrant fallback.")

    wiki_sub.add_parser("status", help="Show wiki compilation status.")

    wiki_list = wiki_sub.add_parser("list", help="List wiki articles.")
    wiki_list.add_argument("--type", choices=["entity", "topic", "source"])

    wiki_get = wiki_sub.add_parser("get", help="Show a wiki article.")
    wiki_get.add_argument("article_id", help="Article ID (slug).")

    for p in [wiki_ingest, wiki_compile, wiki_search, wiki_list, wiki_get]:
        p.add_argument("--provider", choices=["ollama", "claude"], help="LLM provider override.")
        p.add_argument("--model", help="LLM model override.")

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = _normalize_global_flags(argv or sys.argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    store = TaskStore(LegionPaths.discover(args.vault_root))

    if args.command == "bootstrap":
        created = store.bootstrap()
        if created:
            print("Bootstrapped:")
            for path in created:
                print(path)
        else:
            print("Layout already present.")
        return 0

    if args.command == "capture":
        task = store.capture(
            args.title,
            summary=args.summary,
            status=args.status,
            priority=args.priority,
            assignee=args.assignee,
            created_by=args.created_by,
            project=args.project,
            area=args.area,
            lane=args.lane,
            effort=args.effort,
            due=_parse_optional_date(args.due),
            scheduled=_parse_optional_date(args.scheduled),
            source_note=args.source_note,
            tags=args.tag,
            blockers=args.blocker,
            acceptance=args.accept,
        )
        print(f"Created {task.task_id}")
        print(task.path)
        if args.refresh:
            _print_generated(store.refresh())
        return 0

    if args.command == "list":
        tasks = store.list_tasks(
            statuses=args.status or None,
            assignee=args.assignee,
            project=args.project,
            include_done=args.include_done,
        )
        _emit_tasks(tasks, args.format)
        return 0

    if args.command == "next":
        tasks = store.next_tasks(assignee=args.assignee, limit=args.limit)
        _emit_tasks(tasks, args.format)
        return 0

    if args.command == "claim":
        task = store.claim_task(args.task_id, args.assignee, status=args.status)
        print(f"Claimed {task.task_id} for {task.assignee} ({task.status})")
        if args.refresh:
            _print_generated(store.refresh())
        return 0

    if args.command == "update":
        due = None
        if args.clear_due:
            due = object()
        elif args.due:
            due = _parse_optional_date(args.due)
        scheduled = None
        if args.clear_scheduled:
            scheduled = object()
        elif args.scheduled:
            scheduled = _parse_optional_date(args.scheduled)
        source_note = None
        if args.clear_source_note:
            source_note = object()
        elif args.source_note:
            source_note = args.source_note
        task = store.update_task(
            args.task_id,
            status=args.status,
            priority=args.priority,
            assignee=args.assignee,
            project=args.project,
            area=args.area,
            lane=args.lane,
            effort=args.effort,
            due=due,
            scheduled=scheduled,
            summary=args.summary,
            source_note=source_note,
            add_tags=args.add_tag,
            add_blockers=args.add_blocker,
            add_acceptance=args.accept,
            log_note=args.log_note,
        )
        print(f"Updated {task.task_id}")
        if args.refresh:
            _print_generated(store.refresh())
        return 0

    if args.command == "done":
        task = store.complete_task(args.task_id, note=args.note)
        print(f"Completed {task.task_id}")
        if args.refresh:
            _print_generated(store.refresh())
        return 0

    if args.command == "refresh":
        _print_generated(store.refresh())
        return 0

    if args.command == "doctor":
        print(json.dumps(store.doctor(), indent=2))
        return 0

    if args.command == "wiki":
        return _handle_wiki(args, store)

    parser.error(f"Unsupported command: {args.command}")
    return 2


def _handle_wiki(args, task_store: TaskStore) -> int:
    from .wiki_compiler import WikiCompiler
    from .wiki_store import WikiStore

    paths = task_store.paths
    compiler_kwargs: dict = {}
    if getattr(args, "provider", None):
        compiler_kwargs["provider"] = args.provider
    if getattr(args, "model", None):
        compiler_kwargs["model"] = args.model

    tier = getattr(args, "tier", None)
    if tier:
        compiler_kwargs["tier"] = tier
    if compiler_kwargs:
        compiler = WikiCompiler(**compiler_kwargs)
    else:
        compiler = None
    wiki = WikiStore(paths, compiler=compiler)

    if args.wiki_command == "bootstrap":
        created = wiki.bootstrap()
        if created:
            print("Wiki bootstrapped:")
            for path in created:
                print(f"  {path}")
        else:
            print("Wiki layout already present.")
        return 0

    if args.wiki_command == "ingest":
        raw_path = args.path.expanduser().resolve()
        articles = wiki.ingest(raw_path)
        if articles:
            print(f"Ingested {len(articles)} article(s):")
            for article in articles:
                print(f"  {article.article_id} ({article.article_type}) -- {article.summary}")
        else:
            print("Already up to date.")
        return 0

    if args.wiki_command == "compile":
        dry_run = getattr(args, "dry_run", False)
        vault_wide = getattr(args, "vault_wide", False)
        if vault_wide:
            articles = wiki.compile_vault(dry_run=dry_run)
        else:
            articles = wiki.compile_all(dry_run=dry_run)
        if dry_run:
            return 0
        if articles:
            print(f"Compiled {len(articles)} article(s):")
            for article in articles:
                print(f"  {article.article_id} ({article.article_type})")
        else:
            print("Nothing to compile.")
        return 0

    if args.wiki_command == "search":
        deep = getattr(args, "deep", False)
        results = wiki.search(args.query, limit=args.limit, deep=deep)
        if not results:
            print("No results.")
            return 0
        for article in results:
            print(f"  {article.article_id} ({article.article_type}) -- {article.summary}")
        return 0

    if args.wiki_command == "status":
        print(json.dumps(wiki.status(), indent=2))
        return 0

    if args.wiki_command == "list":
        articles = wiki.list_articles(article_type=getattr(args, "type", None))
        if not articles:
            print("No articles.")
            return 0
        for article in articles:
            print(f"  {article.article_id} ({article.article_type}) -- {article.summary}")
        return 0

    if args.wiki_command == "get":
        try:
            article = wiki.get_article(args.article_id)
        except KeyError:
            print(f"Article not found: {args.article_id}")
            return 1
        print(article.to_markdown())
        return 0

    return 2


def _emit_tasks(tasks, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps([task.to_dict() for task in tasks], indent=2))
        return
    if output_format == "ids":
        for task in tasks:
            print(task.task_id)
        return
    if not tasks:
        print("No tasks.")
        return
    for task in tasks:
        due = task.due.isoformat() if task.due else "-"
        print(
            f"{task.task_id} | {task.status:<11} | {task.priority} | {task.assignee:<12} | {due} | {task.title}"
        )


def _print_generated(paths) -> None:
    print("Generated:")
    for path in paths:
        print(path)


def _parse_optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def _normalize_global_flags(argv: list[str]) -> list[str]:
    if not argv:
        return argv

    normalized = list(argv)
    if "--vault-root" in normalized:
        index = normalized.index("--vault-root")
        if index > 0 and index + 1 < len(normalized):
            value = normalized[index + 1]
            del normalized[index : index + 2]
            normalized = ["--vault-root", value, *normalized]
    else:
        for index, item in enumerate(list(normalized)):
            if item.startswith("--vault-root=") and index > 0:
                del normalized[index]
                normalized = [item, *normalized]
                break
    return normalized


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
