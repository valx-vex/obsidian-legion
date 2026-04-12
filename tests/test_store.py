from __future__ import annotations

from pathlib import Path

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
