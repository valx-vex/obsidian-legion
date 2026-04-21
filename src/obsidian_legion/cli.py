from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import nullcontext
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .config import LegionPaths
from .models import Task
from .store import TaskStore

DEBUG_ENV_VAR = "OBSIDIAN_LEGION_DEBUG"


class CliError(Exception):
    def __init__(self, message: str, *, hint: str | None = None, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.exit_code = exit_code


class CliUI:
    def __init__(self, rich_bundle: dict[str, Any] | None = None) -> None:
        self._rich = rich_bundle if rich_bundle is not None else _load_rich_bundle()
        self._console = None
        self._stderr_console = None
        if self._rich is not None:
            console_cls = self._rich["Console"]
            self._console = console_cls(highlight=False, soft_wrap=True)
            self._stderr_console = console_cls(stderr=True, highlight=False, soft_wrap=True)

    @property
    def rich_enabled(self) -> bool:
        return self._rich is not None

    def blank(self) -> None:
        self.print("")

    def print(self, renderable: Any = "", *, stderr: bool = False, raw: bool = False) -> None:
        if self._console is not None and not raw:
            console = self._stderr_console if stderr else self._console
            console.print(renderable)
            return
        stream = sys.stderr if stderr else sys.stdout
        print(str(renderable), file=stream)

    def emit(self, level: str, message: str, *, stderr: bool = False) -> None:
        labels = {
            "success": ("OK", "green"),
            "info": ("Info:", "cyan"),
            "warning": ("Warning:", "yellow"),
            "error": ("Error:", "bold red"),
        }
        label, style = labels[level]
        if self._rich is not None:
            text_cls = self._rich["Text"]
            text = text_cls()
            text.append(label, style=style)
            if message:
                text.append(f" {message}")
            self.print(text, stderr=stderr)
            return
        prefix = label if not message else f"{label} {message}"
        self.print(prefix, stderr=stderr)

    def success(self, message: str) -> None:
        self.emit("success", message)

    def info(self, message: str) -> None:
        self.emit("info", message)

    def warning(self, message: str) -> None:
        self.emit("warning", message)

    def error(self, message: str) -> None:
        self.emit("error", message, stderr=True)

    def headline(self, title: str) -> None:
        if self._rich is not None:
            text = self._rich["Text"](title, style="bold")
            self.print(text)
            return
        self.print(title)

    def status(self, message: str):
        if self._console is None:
            return nullcontext()
        return self._console.status(message, spinner="dots")

    def render_task_table(self, tasks: list[Task]) -> None:
        if not tasks:
            self.info("No tasks.")
            return

        if self._rich is None:
            for task in tasks:
                due = task.due.isoformat() if task.due else "-"
                self.print(
                    f"{task.task_id} | {task.status:<11} | {task.priority} | "
                    f"{task.assignee:<12} | {due} | {task.title}"
                )
            return

        table_cls = self._rich["Table"]
        box = self._rich["box"]
        table = table_cls(box=box.SIMPLE_HEAVY, header_style="bold")
        table.add_column("Task", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Priority", no_wrap=True)
        table.add_column("Assignee", no_wrap=True)
        table.add_column("Due", no_wrap=True)
        table.add_column("Title")

        for task in tasks:
            table.add_row(
                task.task_id,
                self._task_status_cell(task.status),
                self._priority_cell(task.priority),
                task.assignee,
                self._due_cell(task.due),
                task.title,
            )

        self.print(table)

    def render_doctor(self, report: dict[str, Any], output_format: str) -> None:
        if output_format == "json":
            self.print(json.dumps(report, indent=2), raw=True)
            return

        summary = report["summary"]
        self.headline("Obsidian Legion Doctor")
        self.print(
            f"Vault: {report['paths']['vault_root']}  |  "
            f"Tasks: {summary['task_count']} total / {summary['open_tasks']} open"
        )
        self.print(
            f"Summary: {summary['ok']} ok, {summary['warn']} warning(s), {summary['error']} error(s)"
        )
        self.blank()

        if self._rich is not None:
            table_cls = self._rich["Table"]
            box = self._rich["box"]
            table = table_cls(box=box.SIMPLE_HEAVY, header_style="bold")
            table.add_column("Status", no_wrap=True)
            table.add_column("Check", no_wrap=True)
            table.add_column("Details")
            table.add_column("Fix")
            for check in report["checks"]:
                table.add_row(
                    self._doctor_status_cell(check["status"]),
                    check["name"],
                    check["detail"],
                    check.get("fix") or "-",
                )
            self.print(table)
            return

        for check in report["checks"]:
            label = {"ok": "OK", "warn": "WARN", "error": "FAIL"}[check["status"]]
            line = f"{label:<5} {check['name']}: {check['detail']}"
            if check.get("fix"):
                line += f" | Fix: {check['fix']}"
            self.print(line)

    def _doctor_status_cell(self, status: str):
        labels = {
            "ok": ("green", "OK"),
            "warn": ("yellow", "WARN"),
            "error": ("bold red", "FAIL"),
        }
        style, label = labels[status]
        return self._rich_text(label, style=style)

    def _task_status_cell(self, status: str):
        styles = {
            "in_progress": "cyan",
            "ready": "green",
            "inbox": "blue",
            "waiting": "yellow",
            "blocked": "bold red",
            "done": "green",
            "cancelled": "dim",
        }
        return self._rich_text(status, style=styles.get(status, "white"))

    def _priority_cell(self, priority: str):
        styles = {
            "P0": "bold red",
            "P1": "red",
            "P2": "yellow",
            "P3": "green",
        }
        return self._rich_text(priority, style=styles.get(priority, "white"))

    def _due_cell(self, due: date | None):
        if due is None:
            return self._rich_text("-", style="dim")

        today = date.today()
        if due < today:
            style = "bold red"
        elif due <= today + timedelta(days=3):
            style = "yellow"
        else:
            style = "green"
        return self._rich_text(due.isoformat(), style=style)

    def _rich_text(self, value: str, *, style: str):
        if self._rich is None:
            return value
        return self._rich["Text"](value, style=style)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vault-native task engine for the Obsidian legion.")
    parser.add_argument("--vault-root", type=Path, help="Absolute path to the vault root.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("bootstrap", help="Create required task-system directories and state files.")

    subparsers.add_parser(
        "init",
        help="Set up Obsidian Legion in your vault. Auto-detects vault, creates task structure, shows next steps.",
    )

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
    doctor = subparsers.add_parser("doctor", help="Check vault health, optional dependencies, and MCP readiness.")
    doctor.add_argument("--format", choices=["human", "json"], default="human")

    wiki = subparsers.add_parser("wiki", help="LLM Wiki commands (Karpathy pattern).")
    wiki_sub = wiki.add_subparsers(dest="wiki_command", required=True)

    wiki_sub.add_parser("bootstrap", help="Create wiki/ and raw/ directories with seed files.")

    wiki_ingest = wiki_sub.add_parser("ingest", help="Ingest a raw file into the wiki.")
    wiki_ingest.add_argument("path", type=Path, help="Path to raw file.")

    wiki_compile = wiki_sub.add_parser("compile", help="Compile all new/changed raw files.")
    wiki_compile.add_argument("--dry-run", action="store_true", help="Show what would be compiled.")
    wiki_compile.add_argument("--vault-wide", action="store_true", help="Scan entire vault instead of just raw/.")
    wiki_compile.add_argument("--public", action="store_true", help="Compile only non-ignored files into wiki-public/.")
    wiki_compile.add_argument(
        "--tier",
        choices=["heavy", "light"],
        default=None,
        help="Compilation tier (heavy=detailed, light=fast).",
    )

    wiki_search = wiki_sub.add_parser("search", help="Search wiki articles.")
    wiki_search.add_argument("query", help="Search query.")
    wiki_search.add_argument("--limit", type=int, default=10)
    wiki_search.add_argument("--deep", action="store_true", help="Enable deep vector search via Qdrant fallback.")

    wiki_sub.add_parser("status", help="Show wiki compilation status.")

    wiki_list = wiki_sub.add_parser("list", help="List wiki articles.")
    wiki_list.add_argument("--type", choices=["entity", "topic", "source"])

    wiki_export = wiki_sub.add_parser("export", help="Export public wiki to an external directory.")
    wiki_export.add_argument("output_dir", type=Path, help="Output directory for exported wiki.")

    wiki_get = wiki_sub.add_parser("get", help="Show a wiki article.")
    wiki_get.add_argument("article_id", help="Article ID (slug).")

    for subparser in [wiki_ingest, wiki_compile, wiki_search, wiki_list, wiki_get, wiki_export]:
        subparser.add_argument("--provider", choices=["ollama", "claude", "gemini"], help="LLM provider override.")
        subparser.add_argument("--model", help="LLM model override.")

    graphify_p = subparsers.add_parser(
        "graphify",
        help="Layer 0: Build knowledge graph from vault (requires graphifyy package).",
    )
    graphify_p.add_argument("path", nargs="?", help="Path to scan (default: vault root)")
    graphify_p.add_argument("--mode", choices=["deep", "fast"], default="deep", help="Extraction depth")
    graphify_p.add_argument("--update", action="store_true", help="Only process new/changed files")
    graphify_p.add_argument("--query", type=str, help="Query the built graph instead of building")

    return parser


def main(argv: list[str] | None = None) -> int:
    normalized_argv = _normalize_global_flags(argv or sys.argv[1:])
    parser = build_parser()
    ui = _build_ui()

    try:
        args = parser.parse_args(normalized_argv)
        return _dispatch(args, parser, ui)
    except KeyboardInterrupt:
        if _debug_enabled():
            raise
        ui.error("Interrupted.")
        return 130
    except Exception as exc:  # pragma: no cover - exercised via specific error mappings
        if _debug_enabled():
            raise
        friendly = _friendly_error(exc)
        if friendly is None:
            raise
        _emit_cli_error(ui, friendly)
        return friendly.exit_code


def _dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser, ui: CliUI) -> int:
    store = TaskStore(LegionPaths.discover(args.vault_root))

    if args.command == "bootstrap":
        created = store.bootstrap()
        if created:
            ui.success("Bootstrapped task-system layout.")
            for path in created:
                ui.print(path)
        else:
            ui.info("Layout already present.")
        return 0

    if args.command == "init":
        _run_init(store, ui)
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
        ui.success(f"Created {task.task_id}")
        if task.path is not None:
            ui.print(task.path)
        if args.refresh:
            _print_generated(ui, store.refresh())
        return 0

    if args.command == "list":
        tasks = store.list_tasks(
            statuses=args.status or None,
            assignee=args.assignee,
            project=args.project,
            include_done=args.include_done,
        )
        _emit_tasks(tasks, args.format, ui)
        return 0

    if args.command == "next":
        tasks = store.next_tasks(assignee=args.assignee, limit=args.limit)
        _emit_tasks(tasks, args.format, ui)
        return 0

    if args.command == "claim":
        task = store.claim_task(args.task_id, args.assignee, status=args.status)
        ui.success(f"Claimed {task.task_id} for {task.assignee} ({task.status})")
        if args.refresh:
            _print_generated(ui, store.refresh())
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
        ui.success(f"Updated {task.task_id}")
        if args.refresh:
            _print_generated(ui, store.refresh())
        return 0

    if args.command == "done":
        task = store.complete_task(args.task_id, note=args.note)
        ui.success(f"Completed {task.task_id}")
        if args.refresh:
            _print_generated(ui, store.refresh())
        return 0

    if args.command == "refresh":
        _print_generated(ui, store.refresh())
        return 0

    if args.command == "doctor":
        ui.render_doctor(store.doctor(), args.format)
        return 0

    if args.command == "wiki":
        return _handle_wiki(args, store, ui)

    if args.command == "graphify":
        from .graphify import build_graph, is_available, query_graph

        if not is_available():
            raise CliError("Graphify is not installed.", hint="Install with: pip install graphifyy")

        vault_root = store.paths.vault_root
        if args.query:
            ui.print(query_graph(args.query, vault_root))
            return 0

        scan_path = Path(args.path) if args.path else None
        with ui.status("Building graph from the vault..."):
            result = build_graph(vault_root, mode=args.mode, update=args.update, path=scan_path)

        if result.error and not result.success:
            raise CliError(f"Graphify failed: {result.error}")

        ui.success(
            f"Graph built: {result.node_count} nodes, {result.edge_count} edges, "
            f"{result.community_count} communities"
        )
        ui.print(f"Output: {result.output_dir}")
        if result.error:
            ui.warning(result.error)
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


def _run_init(store: TaskStore, ui: CliUI) -> None:
    ui.blank()
    ui.headline("Obsidian Legion -- Setup Wizard")
    ui.blank()
    ui.print(f"Vault: {store.paths.vault_root}")
    ui.blank()
    ui.print("Setting up task system...")
    created = store.bootstrap()
    if created:
        for path in created:
            ui.success(f"Created {path}")
    else:
        ui.info("Task system already set up.")

    ui.blank()
    ui.print("Checking optional features...")
    for ok, label, fix in [
        (_module_available("rich"), "Rich TUI polish", "pip install obsidian-legion[tui]"),
        (_module_available("httpx"), "Wiki compiler (httpx)", "pip install obsidian-legion[wiki]"),
        (_module_available("mcp"), "MCP server", "pip install obsidian-legion[mcp]"),
        (_command_available("graphify"), "Graphify (Layer 0)", "pip install graphifyy"),
        (_module_available("qdrant_client"), "Qdrant (Layer 3)", "pip install obsidian-legion[all]"),
    ]:
        if ok:
            ui.success(label)
        else:
            ui.warning(f"{label}: install with {fix}")

    ui.blank()
    ui.print("Ready. Try:")
    ui.print("  obsidian-legion capture 'My first task' --summary 'Get started'")
    ui.print("  obsidian-legion next")
    ui.print("  obsidian-legion wiki compile")
    ui.print("  obsidian-legion graphify --update")
    ui.blank()
    ui.print("Docs: https://github.com/valx-vex/obsidian-legion")
    ui.blank()
    ui.print("One contract. Every agent. Zero sludge.")
    ui.blank()


def _handle_wiki(args: argparse.Namespace, task_store: TaskStore, ui: CliUI) -> int:
    from .wiki_compiler import WikiCompiler
    from .wiki_store import WikiStore

    paths = task_store.paths
    compiler_kwargs: dict[str, Any] = {}
    if getattr(args, "provider", None):
        compiler_kwargs["provider"] = args.provider
    if getattr(args, "model", None):
        compiler_kwargs["model"] = args.model

    tier = getattr(args, "tier", None)
    if tier:
        compiler_kwargs["tier"] = tier

    compiler = WikiCompiler(**compiler_kwargs) if compiler_kwargs else None
    wiki = WikiStore(paths, compiler=compiler)

    if args.wiki_command == "bootstrap":
        created = wiki.bootstrap()
        if created:
            ui.success("Wiki bootstrapped.")
            for path in created:
                ui.print(f"  {path}")
        else:
            ui.info("Wiki layout already present.")
        return 0

    if args.wiki_command == "ingest":
        raw_path = args.path.expanduser().resolve()
        with ui.status(f"Ingesting {raw_path.name}..."):
            articles = wiki.ingest(raw_path)
        if articles:
            ui.success(f"Ingested {len(articles)} article(s).")
            for article in articles:
                ui.print(f"  {article.article_id} ({article.article_type}) -- {article.summary}")
        else:
            ui.info("Already up to date.")
        return 0

    if args.wiki_command == "compile":
        dry_run = getattr(args, "dry_run", False)
        vault_wide = getattr(args, "vault_wide", False)
        public = getattr(args, "public", False)

        status_message = "Compiling wiki articles..."
        if public:
            status_message = "Compiling public wiki..."
        elif vault_wide:
            status_message = "Compiling vault-wide wiki articles..."

        with ui.status(status_message) if not dry_run else nullcontext():
            if public:
                articles = wiki.compile_public(dry_run=dry_run)
            elif vault_wide:
                articles = wiki.compile_vault(dry_run=dry_run)
            else:
                articles = wiki.compile_all(dry_run=dry_run)

        if dry_run:
            return 0
        if articles:
            ui.success(f"Compiled {len(articles)} article(s).")
            for article in articles:
                ui.print(f"  {article.article_id} ({article.article_type})")
        else:
            ui.info("Nothing to compile.")
        return 0

    if args.wiki_command == "export":
        output_dir = args.output_dir.expanduser().resolve()
        with ui.status(f"Exporting public wiki to {output_dir}..."):
            exported = wiki.export_public(output_dir)
        if exported:
            ui.success(f"Exported {len(exported)} file(s) to {output_dir}.")
            for path in exported:
                ui.print(f"  {path}")
        else:
            ui.info("Nothing to export.")
        return 0

    if args.wiki_command == "search":
        deep = getattr(args, "deep", False)
        results = wiki.search(args.query, limit=args.limit, deep=deep)
        if not results:
            ui.info("No results.")
            return 0
        for article in results:
            ui.print(f"  {article.article_id} ({article.article_type}) -- {article.summary}")
        return 0

    if args.wiki_command == "status":
        ui.print(json.dumps(wiki.status(), indent=2))
        return 0

    if args.wiki_command == "list":
        articles = wiki.list_articles(article_type=getattr(args, "type", None))
        if not articles:
            ui.info("No articles.")
            return 0
        for article in articles:
            ui.print(f"  {article.article_id} ({article.article_type}) -- {article.summary}")
        return 0

    if args.wiki_command == "get":
        article = wiki.get_article(args.article_id)
        ui.print(article.to_markdown())
        return 0

    return 2


def _emit_tasks(tasks: list[Task], output_format: str, ui: CliUI) -> None:
    if output_format == "json":
        ui.print(json.dumps([task.to_dict() for task in tasks], indent=2))
        return
    if output_format == "ids":
        for task in tasks:
            ui.print(task.task_id)
        return
    ui.render_task_table(tasks)


def _print_generated(ui: CliUI, paths: list[Path]) -> None:
    ui.success("Generated:")
    for path in paths:
        ui.print(path)


def _parse_optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CliError(
            f"Invalid date: {value}",
            hint="Use YYYY-MM-DD, for example: 2026-04-21",
        ) from exc


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


def _build_ui() -> CliUI:
    return CliUI()


def _load_rich_bundle() -> dict[str, Any] | None:
    try:
        from rich import box
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text
    except ImportError:
        return None
    return {
        "Console": Console,
        "Table": Table,
        "Text": Text,
        "box": box,
    }


def _friendly_error(exc: Exception) -> CliError | None:
    if isinstance(exc, CliError):
        return exc

    if isinstance(exc, FileNotFoundError):
        message = _exception_message(exc)
        if "Could not discover vault root" in message:
            return CliError(
                "No vault found.",
                hint="Try: obsidian-legion init --vault-root ~/my-vault",
            )
        if "does not look like an Obsidian vault root" in message:
            return CliError(
                "That path does not look like an Obsidian vault.",
                hint="Make sure it contains .obsidian/ and 06-daily/action-points/, or run obsidian-legion init --vault-root <path>",
            )
        if message.startswith("Raw file not found:"):
            raw_path = message.split("Raw file not found:", 1)[1].strip()
            return CliError(
                f"Raw file not found: {raw_path}",
                hint="Add the file under raw/ or pass the correct path to obsidian-legion wiki ingest.",
            )
        return CliError(message)

    if isinstance(exc, KeyError):
        message = _exception_message(exc)
        if message.startswith("Task not found:"):
            task_id = message.split("Task not found:", 1)[1].strip()
            return CliError(
                f"Task not found: {task_id}",
                hint="Try: obsidian-legion list --format ids",
            )
        if message.startswith("Article not found:"):
            article_id = message.split("Article not found:", 1)[1].strip()
            return CliError(
                f"Article not found: {article_id}",
                hint="Try: obsidian-legion wiki list",
            )
        return CliError(message)

    if isinstance(exc, ValueError):
        message = _exception_message(exc)
        if message.startswith(("Invalid status:", "Invalid priority:", "Invalid lane:", "Invalid effort:")):
            return CliError(message, hint="Run the command with --help to see allowed values.")
        return None

    if isinstance(exc, ImportError):
        module_name = getattr(exc, "name", "") or ""
        hints = {
            "mcp": "pip install obsidian-legion[mcp]",
            "qdrant_client": "pip install obsidian-legion[all]",
            "httpx": "pip install obsidian-legion[wiki]",
        }
        if module_name in hints:
            return CliError(
                f"Missing optional dependency: {module_name}",
                hint=f"Install with: {hints[module_name]}",
            )

    return None


def _emit_cli_error(ui: CliUI, error: CliError) -> None:
    ui.error(error.message)
    if error.hint:
        ui.emit("info", error.hint, stderr=True)


def _exception_message(exc: BaseException) -> str:
    if exc.args and isinstance(exc.args[0], str):
        return exc.args[0]
    return str(exc)


def _debug_enabled() -> bool:
    value = os.environ.get(DEBUG_ENV_VAR, "")
    return value.lower() not in {"", "0", "false", "no"}


def _module_available(module_name: str) -> bool:
    try:
        __import__(module_name)
    except ImportError:
        return False
    return True


def _command_available(command_name: str) -> bool:
    from shutil import which

    return which(command_name) is not None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
