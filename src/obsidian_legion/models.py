from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


VALID_STATUSES = (
    "inbox",
    "ready",
    "in_progress",
    "waiting",
    "blocked",
    "done",
    "cancelled",
)
VALID_PRIORITIES = ("P0", "P1", "P2", "P3")
VALID_LANES = ("today", "this-week", "backlog", "someday")
VALID_EFFORTS = ("s", "m", "l", "xl")


@dataclass(slots=True)
class Task:
    task_id: str
    title: str
    summary: str
    status: str = "inbox"
    priority: str = "P2"
    assignee: str = "unassigned"
    created_by: str = "human"
    project: str = "general"
    area: str = "general"
    lane: str = "backlog"
    effort: str = "m"
    created_at: datetime = field(default_factory=lambda: datetime.now().astimezone())
    updated_at: datetime = field(default_factory=lambda: datetime.now().astimezone())
    completed_at: datetime | None = None
    due: date | None = None
    scheduled: date | None = None
    source_note: str | None = None
    tags: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    path: Path | None = None

    def validate(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {self.status}")
        if self.priority not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {self.priority}")
        if self.lane not in VALID_LANES:
            raise ValueError(f"Invalid lane: {self.lane}")
        if self.effort not in VALID_EFFORTS:
            raise ValueError(f"Invalid effort: {self.effort}")

    def to_metadata(self) -> dict[str, Any]:
        self.validate()
        data: dict[str, Any] = {
            "task_id": self.task_id,
            "title": self.title,
            "summary": self.summary,
            "status": self.status,
            "priority": self.priority,
            "assignee": self.assignee,
            "created_by": self.created_by,
            "project": self.project,
            "area": self.area,
            "lane": self.lane,
            "effort": self.effort,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "due": self.due.isoformat() if self.due else None,
            "scheduled": self.scheduled.isoformat() if self.scheduled else None,
            "source_note": self.source_note,
            "tags": self.tags,
            "blockers": self.blockers,
            "acceptance": self.acceptance,
            "log": self.log,
        }
        return data

    def to_dict(self) -> dict[str, Any]:
        data = self.to_metadata()
        if self.path is not None:
            data["path"] = str(self.path)
        return data

    @property
    def is_open(self) -> bool:
        return self.status not in {"done", "cancelled"}
