from __future__ import annotations

from pathlib import Path

import pytest

from obsidian_legion.config import LegionPaths
from obsidian_legion.store import TaskStore


def make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "06-daily" / "action-points").mkdir(parents=True)
    return vault


def test_capture_and_refresh(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    store = TaskStore(LegionPaths.discover(vault))

    store.bootstrap()
    task = store.capture(
        "Build the system",
        summary="Ship the first version of the canonical task system.",
        project="obsidian-legion",
        area="vexnet",
        assignee="codex",
        acceptance=["CLI works", "Dashboards render"],
    )

    assert task.path is not None
    assert task.path.exists()

    refreshed = store.refresh()
    assert any(path.name == "LEGION_TASK_BOARD.md" for path in refreshed)
    board = (vault / "06-daily" / "action-points" / "dashboards" / "LEGION_TASK_BOARD.md").read_text(
        encoding="utf-8"
    )
    assert "Build the system" in board
    assert task.task_id in board


def test_claim_and_complete(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    store = TaskStore(LegionPaths.discover(vault))
    task = store.capture("Claimable task", summary="Claim me.")

    claimed = store.claim_task(task.task_id, "codex")
    assert claimed.assignee == "codex"
    assert claimed.status == "in_progress"

    done = store.complete_task(task.task_id, note="Finished in test.")
    assert done.status == "done"
    assert done.completed_at is not None


def test_doctor_reports_structured_health(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = make_vault(tmp_path)
    store = TaskStore(LegionPaths.discover(vault))
    store.bootstrap()
    store.paths.agents_file.write_text("agents:\n  - codex\n", encoding="utf-8")
    store.capture("Doctor task", summary="Give doctor a task count.")

    availability = {
        "rich": True,
        "httpx": True,
        "mcp": True,
        "qdrant_client": True,
    }

    def fake_module_available(module_name: str) -> bool:
        return availability.get(module_name, False)

    def fake_which(command_name: str) -> str | None:
        values = {
            "obsidian": "/usr/local/bin/obsidian",
            "graphify": "/usr/local/bin/graphify",
        }
        return values.get(command_name)

    monkeypatch.setattr("obsidian_legion.store._module_available", fake_module_available)
    monkeypatch.setattr("obsidian_legion.store.shutil.which", fake_which)
    monkeypatch.setattr("obsidian_legion.store._probe_obsidian_daily_path", lambda _bin: "/vault/daily.md")
    monkeypatch.setattr(
        "obsidian_legion.store._run_mcp_smoke_test",
        lambda _paths: {
            "code": "mcp_smoke",
            "name": "MCP smoke test",
            "status": "ok",
            "detail": "MCP server imports and builds successfully.",
            "fix": None,
        },
    )

    report = store.doctor()
    checks = {check["code"]: check for check in report["checks"]}

    assert report["status"] == "ok"
    assert report["summary"]["task_count"] == 1
    assert report["summary"]["open_tasks"] == 1
    assert checks["rich"]["status"] == "ok"
    assert checks["graphify"]["status"] == "ok"
    assert checks["mcp_smoke"]["status"] == "ok"
    assert checks["obsidian_daily"]["detail"] == "/vault/daily.md"


def test_doctor_flags_missing_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = make_vault(tmp_path)
    store = TaskStore(LegionPaths.discover(vault))

    monkeypatch.setattr("obsidian_legion.store._module_available", lambda _name: False)
    monkeypatch.setattr("obsidian_legion.store.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "obsidian_legion.store._run_mcp_smoke_test",
        lambda _paths: {
            "code": "mcp_smoke",
            "name": "MCP smoke test",
            "status": "warn",
            "detail": "MCP dependency is not installed.",
            "fix": "Install with: pip install obsidian-legion[mcp]",
        },
    )

    report = store.doctor()
    checks = {check["code"]: check for check in report["checks"]}

    assert report["status"] == "error"
    assert checks["tasks_root"]["status"] == "error"
    assert checks["rich"]["status"] == "warn"
    assert checks["mcp_smoke"]["status"] == "warn"
