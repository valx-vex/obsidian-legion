from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .config import LegionPaths
from .models import Task

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix fallback
    fcntl = None


STATUS_ORDER = {
    "in_progress": 0,
    "ready": 1,
    "inbox": 2,
    "waiting": 3,
    "blocked": 4,
    "done": 5,
    "cancelled": 6,
}
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


class TaskStore:
    def __init__(self, paths: LegionPaths):
        self.paths = paths

    def bootstrap(self) -> list[Path]:
        self.paths.ensure_layout()
        created: list[Path] = []
        if not self.paths.counter_file.exists():
            self._write_text_atomic(
                self.paths.counter_file,
                json.dumps({"date": None, "value": 0}, indent=2) + "\n",
            )
            created.append(self.paths.counter_file)
        return created

    def capture(
        self,
        title: str,
        *,
        summary: str,
        status: str = "inbox",
        priority: str = "P2",
        assignee: str = "unassigned",
        created_by: str = "human",
        project: str = "general",
        area: str = "general",
        lane: str = "backlog",
        effort: str = "m",
        due: date | None = None,
        scheduled: date | None = None,
        source_note: str | None = None,
        tags: list[str] | None = None,
        blockers: list[str] | None = None,
        acceptance: list[str] | None = None,
    ) -> Task:
        self.bootstrap()
        now = datetime.now().astimezone()
        task_id = self._allocate_task_id(now)
        relative_path = Path("06-daily") / "action-points" / "tasks" / now.strftime("%Y") / now.strftime("%m")
        slug = _slugify(title)
        task_path = self.paths.vault_root / relative_path / f"{task_id}_{slug}.md"
        task_path.parent.mkdir(parents=True, exist_ok=True)

        task = Task(
            task_id=task_id,
            title=title.strip(),
            summary=summary.strip(),
            status=status,
            priority=priority,
            assignee=assignee,
            created_by=created_by,
            project=project,
            area=area,
            lane=lane,
            effort=effort,
            created_at=now,
            updated_at=now,
            due=due,
            scheduled=scheduled,
            source_note=source_note,
            tags=_dedupe(tags or []),
            blockers=_dedupe(blockers or []),
            acceptance=[item.strip() for item in acceptance or [] if item.strip()],
            log=[f"{now.isoformat()} Created by {created_by}."],
            path=task_path,
        )
        self.write_task(task)
        return task

    def load_tasks(self) -> list[Task]:
        if not self.paths.tasks_root.exists():
            return []
        tasks: list[Task] = []
        for path in sorted(self.paths.tasks_root.rglob("TASK-*.md")):
            task = self._read_task(path)
            if task is not None:
                tasks.append(task)
        return tasks

    def find_task(self, task_id: str) -> Task:
        normalized = task_id.strip()
        for task in self.load_tasks():
            if task.task_id == normalized:
                return task
        raise KeyError(f"Task not found: {normalized}")

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        project: str | None = None,
        area: str | None = None,
        lane: str | None = None,
        effort: str | None = None,
        due: date | None | object = None,
        scheduled: date | None | object = None,
        summary: str | None = None,
        source_note: str | None | object = None,
        add_tags: list[str] | None = None,
        add_blockers: list[str] | None = None,
        add_acceptance: list[str] | None = None,
        log_note: str | None = None,
    ) -> Task:
        task = self.find_task(task_id)
        now = datetime.now().astimezone()
        if status is not None:
            task.status = status
            if status == "done" and task.completed_at is None:
                task.completed_at = now
            if status != "done":
                task.completed_at = None
        if priority is not None:
            task.priority = priority
        if assignee is not None:
            task.assignee = assignee
        if project is not None:
            task.project = project
        if area is not None:
            task.area = area
        if lane is not None:
            task.lane = lane
        if effort is not None:
            task.effort = effort
        if due is not None:
            task.due = due if isinstance(due, date) else None
        if scheduled is not None:
            task.scheduled = scheduled if isinstance(scheduled, date) else None
        if summary is not None:
            task.summary = summary.strip()
        if source_note is not None:
            task.source_note = source_note if isinstance(source_note, str) else None
        if add_tags:
            task.tags = _dedupe([*task.tags, *add_tags])
        if add_blockers:
            task.blockers = _dedupe([*task.blockers, *add_blockers])
        if add_acceptance:
            task.acceptance = _dedupe([*task.acceptance, *[item.strip() for item in add_acceptance if item.strip()]])
        if log_note:
            task.log.append(f"{now.isoformat()} {log_note.strip()}")
        task.updated_at = now
        self.write_task(task)
        return task

    def claim_task(self, task_id: str, assignee: str, *, status: str = "in_progress") -> Task:
        return self.update_task(
            task_id,
            assignee=assignee,
            status=status,
            log_note=f"Claimed by {assignee}.",
        )

    def complete_task(self, task_id: str, *, note: str | None = None) -> Task:
        task = self.update_task(
            task_id,
            status="done",
            log_note=note or "Marked done.",
        )
        return task

    def list_tasks(
        self,
        *,
        statuses: list[str] | None = None,
        assignee: str | None = None,
        project: str | None = None,
        include_done: bool = False,
    ) -> list[Task]:
        tasks = self.load_tasks()
        filtered: list[Task] = []
        for task in tasks:
            if not include_done and not task.is_open:
                continue
            if statuses and task.status not in statuses:
                continue
            if assignee and task.assignee != assignee:
                continue
            if project and task.project != project:
                continue
            filtered.append(task)
        return sorted(filtered, key=self._sort_key)

    def next_tasks(self, assignee: str | None = None, limit: int = 10) -> list[Task]:
        tasks = []
        for task in self.load_tasks():
            if not task.is_open:
                continue
            if task.status == "blocked":
                continue
            if assignee and task.assignee not in {assignee, "unassigned"}:
                continue
            tasks.append(task)
        return sorted(tasks, key=lambda item: self._next_sort_key(item, assignee))[:limit]

    def refresh(self) -> list[Path]:
        self.bootstrap()
        tasks = self.load_tasks()
        now = datetime.now().astimezone()
        today = now.date()
        generated: list[Path] = []

        board_path = self.paths.dashboards_root / "LEGION_TASK_BOARD.md"
        today_path = self.paths.dashboards_root / "LEGION_TODAY.md"
        week_path = self.paths.dashboards_root / "LEGION_WEEK.md"
        human_daily_path = self.paths.daily_root / now.strftime("%Y") / f"{today.isoformat()}_BELOVED_TASKS.md"
        weekly_review_path = self.paths.reviews_root / f"{today.isocalendar().year}-W{today.isocalendar().week:02d}.md"

        human_daily_path.parent.mkdir(parents=True, exist_ok=True)

        for path, content in [
            (board_path, self._render_board(tasks, now)),
            (today_path, self._render_today(tasks, now)),
            (week_path, self._render_week(tasks, now)),
            (human_daily_path, self._render_human_daily(tasks, now)),
            (weekly_review_path, self._render_weekly_review(tasks, now)),
        ]:
            self._write_text_atomic(path, content)
            generated.append(path)

        return generated

    def doctor(self) -> dict[str, Any]:
        obsidian_bin = shutil.which("obsidian")
        daily_path = None
        if obsidian_bin:
            try:
                result = subprocess.run(
                    [obsidian_bin, "daily:path"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                daily_path = result.stdout.strip() or None
            except subprocess.CalledProcessError:
                daily_path = None
        return {
            "vault_root": str(self.paths.vault_root),
            "action_points_root": str(self.paths.action_points_root),
            "obsidian_cli": obsidian_bin or "missing",
            "daily_path": daily_path,
            "agents_file": str(self.paths.agents_file),
            "tasks_root": str(self.paths.tasks_root),
        }

    def write_task(self, task: Task) -> None:
        if task.path is None:
            raise ValueError("Task path is required for write_task().")
        metadata = yaml.safe_dump(
            task.to_metadata(),
            sort_keys=False,
            allow_unicode=False,
            width=100,
        ).strip()
        content = "\n".join(
            [
                "---",
                metadata,
                "---",
                "",
                f"# {task.title}",
                "",
                task.summary.strip() or "_No summary yet._",
                "",
                "## Acceptance",
                *([f"- [ ] {item}" for item in task.acceptance] or ["- [ ] Define acceptance criteria."]),
                "",
                "## Log",
                *([f"- {entry}" for entry in task.log] or ["- No log entries yet."]),
                "",
            ]
        )
        self._write_text_atomic(task.path, content)

    def _read_task(self, path: Path) -> Task | None:
        text = path.read_text(encoding="utf-8")
        metadata = _parse_frontmatter(text)
        if not metadata or "task_id" not in metadata:
            return None
        task = Task(
            task_id=str(metadata["task_id"]),
            title=str(metadata.get("title", path.stem)),
            summary=str(metadata.get("summary", "")).strip(),
            status=str(metadata.get("status", "inbox")),
            priority=str(metadata.get("priority", "P2")),
            assignee=str(metadata.get("assignee", "unassigned")),
            created_by=str(metadata.get("created_by", "human")),
            project=str(metadata.get("project", "general")),
            area=str(metadata.get("area", "general")),
            lane=str(metadata.get("lane", "backlog")),
            effort=str(metadata.get("effort", "m")),
            created_at=_parse_datetime(metadata.get("created_at")) or datetime.fromtimestamp(path.stat().st_ctime).astimezone(),
            updated_at=_parse_datetime(metadata.get("updated_at")) or datetime.fromtimestamp(path.stat().st_mtime).astimezone(),
            completed_at=_parse_datetime(metadata.get("completed_at")),
            due=_parse_date(metadata.get("due")),
            scheduled=_parse_date(metadata.get("scheduled")),
            source_note=_none_if_empty(metadata.get("source_note")),
            tags=_coerce_str_list(metadata.get("tags")),
            blockers=_coerce_str_list(metadata.get("blockers")),
            acceptance=_coerce_str_list(metadata.get("acceptance")),
            log=_coerce_str_list(metadata.get("log")),
            path=path,
        )
        task.validate()
        return task

    def _allocate_task_id(self, now: datetime) -> str:
        self.paths.counter_file.parent.mkdir(parents=True, exist_ok=True)
        self.paths.counter_file.touch(exist_ok=True)
        if fcntl is None:
            state = self._read_counter_state()
            state = _advance_counter(state, now)
            self._write_text_atomic(self.paths.counter_file, json.dumps(state, indent=2) + "\n")
            return f"TASK-{now.strftime('%Y%m%d')}-{state['value']:03d}"

        with self.paths.counter_file.open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            raw = handle.read().strip()
            state = json.loads(raw) if raw else {"date": None, "value": 0}
            state = _advance_counter(state, now)
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(state, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return f"TASK-{now.strftime('%Y%m%d')}-{state['value']:03d}"

    def _read_counter_state(self) -> dict[str, Any]:
        if not self.paths.counter_file.exists():
            return {"date": None, "value": 0}
        raw = self.paths.counter_file.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else {"date": None, "value": 0}

    def _sort_key(self, task: Task) -> tuple[Any, ...]:
        due_key = task.due or date.max
        scheduled_key = task.scheduled or date.max
        return (
            STATUS_ORDER.get(task.status, 99),
            PRIORITY_ORDER.get(task.priority, 99),
            due_key,
            scheduled_key,
            task.updated_at,
            task.task_id,
        )

    def _next_sort_key(self, task: Task, assignee: str | None) -> tuple[Any, ...]:
        due_days = (task.due - date.today()).days if task.due else 9999
        scheduled_days = (task.scheduled - date.today()).days if task.scheduled else 9999
        assignee_rank = 0
        if assignee and task.assignee != assignee:
            assignee_rank = 1
        return (
            assignee_rank,
            STATUS_ORDER.get(task.status, 99),
            PRIORITY_ORDER.get(task.priority, 99),
            due_days,
            scheduled_days,
            task.created_at,
            task.task_id,
        )

    def _render_board(self, tasks: list[Task], now: datetime) -> str:
        open_tasks = [task for task in tasks if task.is_open]
        blocked = [task for task in open_tasks if task.status in {"blocked", "waiting"}]
        done_recent = sorted(
            [task for task in tasks if task.status == "done"],
            key=lambda item: item.updated_at,
            reverse=True,
        )[:10]

        agent_groups: dict[str, list[Task]] = defaultdict(list)
        for task in open_tasks:
            agent_groups[task.assignee].append(task)

        lines = [
            "# Legion Task Board",
            "",
            f"Generated: {now.isoformat()}",
            "",
            "## Snapshot",
            f"- Open tasks: {len(open_tasks)}",
            f"- In progress: {sum(1 for task in open_tasks if task.status == 'in_progress')}",
            f"- Waiting or blocked: {len(blocked)}",
            f"- Done this week: {sum(1 for task in tasks if task.status == 'done' and task.completed_at and (now.date() - task.completed_at.date()).days <= 7)}",
            "",
            "## Next Queue",
            *_render_task_table(self.next_tasks(limit=12)),
            "",
            "## By Assignee",
        ]
        for assignee in sorted(agent_groups):
            lines.extend(
                [
                    f"### {assignee}",
                    *_render_task_table(sorted(agent_groups[assignee], key=self._sort_key)[:8]),
                    "",
                ]
            )
        lines.extend(
            [
                "## Waiting And Blocked",
                *_render_task_table(sorted(blocked, key=self._sort_key)),
                "",
                "## Recently Done",
                *_render_task_table(done_recent),
                "",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    def _render_today(self, tasks: list[Task], now: datetime) -> str:
        today = now.date()
        focus = [
            task
            for task in tasks
            if task.is_open
            and (
                task.status == "in_progress"
                or task.priority == "P0"
                or task.scheduled == today
                or task.due == today
            )
        ]
        human = [
            task
            for task in tasks
            if task.is_open and (task.assignee in {"human", "unassigned"} or task.status == "waiting")
        ]
        lines = [
            "# Legion Today",
            "",
            f"Date: {today.isoformat()}",
            "",
            "## Focus Now",
            *_render_task_table(sorted(focus, key=self._sort_key)),
            "",
            "## Human Follow Ups",
            *_render_task_table(sorted(human, key=self._sort_key)[:12]),
            "",
            "## Capture Shortcuts",
            "- `./bin/obsidian-legion capture \"Title\" --project <project> --area <area> --refresh`",
            "- `./bin/obsidian-legion next --assignee codex`",
            "- `./bin/obsidian-legion refresh`",
            "",
        ]
        return "\n".join(lines).rstrip() + "\n"

    def _render_week(self, tasks: list[Task], now: datetime) -> str:
        today = now.date()
        week_end = today + timedelta(days=6)
        week_tasks = [
            task
            for task in tasks
            if task.is_open
            and (
                (task.due and today <= task.due <= week_end)
                or (task.scheduled and today <= task.scheduled <= week_end)
                or task.status == "in_progress"
            )
        ]
        by_project: dict[str, list[Task]] = defaultdict(list)
        for task in week_tasks:
            by_project[task.project].append(task)
        lines = [
            "# Legion Week",
            "",
            f"Window: {today.isoformat()} -> {week_end.isoformat()}",
            "",
            "## This Week",
            *_render_task_table(sorted(week_tasks, key=self._sort_key)),
            "",
            "## Project Buckets",
        ]
        for project in sorted(by_project):
            lines.extend(
                [
                    f"### {project}",
                    *_render_task_table(sorted(by_project[project], key=self._sort_key)),
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    def _render_human_daily(self, tasks: list[Task], now: datetime) -> str:
        today = now.date()
        human_priority = [
            task
            for task in tasks
            if task.is_open
            and task.assignee in {"human", "unassigned"}
            and (task.priority in {"P0", "P1"} or task.due == today or task.scheduled == today)
        ]
        human_later = [
            task
            for task in tasks
            if task.is_open
            and task.assignee in {"human", "unassigned"}
            and task not in human_priority
        ]
        waiting = [task for task in tasks if task.is_open and task.status == "waiting"]
        done_recent = [
            task
            for task in sorted(tasks, key=lambda item: item.updated_at, reverse=True)
            if task.status == "done"
        ][:8]
        lines = [
            f"# Beloved Tasks {today.isoformat()}",
            "",
            f"Generated: {now.isoformat()}",
            "",
            "## Priority Tasks",
            *_render_checkbox_list(human_priority),
            "",
            "## When You Have More Time",
            *_render_checkbox_list(human_later),
            "",
            "## Waiting On You",
            *_render_checkbox_list(waiting),
            "",
            "## Recently Completed",
            *_render_checkbox_list(done_recent, checked=True),
            "",
        ]
        return "\n".join(lines).rstrip() + "\n"

    def _render_weekly_review(self, tasks: list[Task], now: datetime) -> str:
        today = now.date()
        iso = today.isocalendar()
        open_tasks = [task for task in tasks if task.is_open]
        by_assignee: dict[str, int] = defaultdict(int)
        for task in open_tasks:
            by_assignee[task.assignee] += 1
        lines = [
            f"# Legion Weekly Review {iso.year}-W{iso.week:02d}",
            "",
            f"Generated: {now.isoformat()}",
            "",
            "## Counts",
            f"- Open tasks: {len(open_tasks)}",
            f"- Done tasks: {sum(1 for task in tasks if task.status == 'done')}",
            f"- Blocked or waiting: {sum(1 for task in open_tasks if task.status in {'blocked', 'waiting'})}",
            "",
            "## Open By Assignee",
        ]
        for assignee, count in sorted(by_assignee.items()):
            lines.append(f"- {assignee}: {count}")
        lines.extend(
            [
                "",
                "## Highest Priority",
                *_render_task_table(
                    sorted(
                        [task for task in open_tasks if task.priority in {"P0", "P1"}],
                        key=self._sort_key,
                    )[:15]
                ),
                "",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    def _write_text_atomic(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as handle:
            handle.write(content)
            temp_name = handle.name
        os.replace(temp_name, path)


def _advance_counter(state: dict[str, Any], now: datetime) -> dict[str, Any]:
    current_date = now.strftime("%Y%m%d")
    if state.get("date") != current_date:
        return {"date": current_date, "value": 1}
    return {"date": current_date, "value": int(state.get("value", 0)) + 1}


def _slugify(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return value or "task"


def _parse_frontmatter(text: str) -> dict[str, Any]:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return {}
    _, _, rest = normalized.partition("\n")
    frontmatter, separator, _ = rest.partition("\n---\n")
    if not separator:
        return {}
    return yaml.safe_load(frontmatter) or {}


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone()
    return datetime.fromisoformat(str(value)).astimezone()


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _none_if_empty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in values:
        item = raw.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _task_link(task: Task) -> str:
    if task.path is None:
        return task.task_id
    relative = _vault_relative(task.path).with_suffix("")
    return f"[[{relative.as_posix()}|{task.task_id}]]"


def _source_link(task: Task) -> str:
    if not task.source_note:
        return "-"
    target = task.source_note.removesuffix(".md")
    return f"[[{target}|source]]"


def _render_task_table(tasks: list[Task]) -> list[str]:
    if not tasks:
        return ["_No matching tasks._"]
    lines = [
        "| Task | Status | Priority | Assignee | Due | Project | Source |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for task in tasks:
        due = task.due.isoformat() if task.due else "-"
        lines.append(
            f"| {_task_link(task)} {task.title} | {task.status} | {task.priority} | {task.assignee} | {due} | {task.project} | {_source_link(task)} |"
        )
    return lines


def _render_checkbox_list(tasks: list[Task], *, checked: bool = False) -> list[str]:
    if not tasks:
        return ["- [ ] Nothing queued."]
    mark = "x" if checked else " "
    lines = []
    for task in tasks:
        due = f" due {task.due.isoformat()}" if task.due else ""
        lines.append(f"- [{mark}] {_task_link(task)} {task.title} ({task.priority}, {task.status}, {task.assignee}){due}")
    return lines


def _vault_relative(path: Path) -> Path:
    for parent in path.parents:
        if (parent / ".obsidian").exists():
            return path.relative_to(parent)
    return Path(path.name)
