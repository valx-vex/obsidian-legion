from __future__ import annotations

import json
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

from obsidian_legion import cli
from obsidian_legion.cli import main


def make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "06-daily" / "action-points").mkdir(parents=True)
    return vault


class FakeText:
    def __init__(self, text: str = "", style: str | None = None) -> None:
        self.parts = [text] if text else []

    def append(self, text: str, style: str | None = None) -> None:
        self.parts.append(text)

    def __str__(self) -> str:
        return "".join(self.parts)


class FakeTable:
    def __init__(self, *args, **kwargs) -> None:
        self.columns: list[str] = []
        self.rows: list[list[str]] = []

    def add_column(self, header: str, **kwargs) -> None:
        self.columns.append(header)

    def add_row(self, *cells) -> None:
        self.rows.append([str(cell) for cell in cells])

    def __str__(self) -> str:
        lines = ["FAKE_RICH_TABLE", " | ".join(self.columns)]
        lines.extend(" | ".join(row) for row in self.rows)
        return "\n".join(lines)


class FakeConsole:
    def __init__(self, *, stderr: bool = False, highlight: bool = False, soft_wrap: bool = False) -> None:
        self.stderr = stderr

    def print(self, renderable="") -> None:
        stream = sys.stderr if self.stderr else sys.stdout
        print(str(renderable), file=stream)

    def status(self, message: str, spinner: str = "dots"):
        return nullcontext()


class FakeBox:
    SIMPLE_HEAVY = object()


def fake_rich_bundle() -> dict[str, object]:
    return {
        "Console": FakeConsole,
        "Table": FakeTable,
        "Text": FakeText,
        "box": FakeBox,
    }


def test_cli_capture_and_done(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = make_vault(tmp_path)

    assert main(["--vault-root", str(vault), "bootstrap"]) == 0
    assert (
        main(
            [
                "--vault-root",
                str(vault),
                "capture",
                "CLI task",
                "--summary",
                "Exercise the CLI.",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Created TASK-" in output
    task_id = next(line.split()[2] for line in output.splitlines() if "Created TASK-" in line)

    assert main(["--vault-root", str(vault), "done", task_id]) == 0
    done_output = capsys.readouterr().out
    assert f"Completed {task_id}" in done_output


def test_cli_missing_vault_is_friendly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["next"]) == 1
    captured = capsys.readouterr()
    assert "No vault found." in captured.err
    assert "obsidian-legion init --vault-root" in captured.err


def test_cli_missing_task_is_friendly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = make_vault(tmp_path)

    assert main(["--vault-root", str(vault), "done", "TASK-20990101-999"]) == 1
    captured = capsys.readouterr()
    assert "Task not found: TASK-20990101-999" in captured.err
    assert "obsidian-legion list --format ids" in captured.err


def test_cli_missing_raw_file_is_friendly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = make_vault(tmp_path)
    missing = vault / "raw" / "missing.md"

    assert main(["--vault-root", str(vault), "wiki", "ingest", str(missing)]) == 1
    captured = capsys.readouterr()
    assert f"Raw file not found: {missing}" in captured.err
    assert "obsidian-legion wiki ingest" in captured.err


def test_cli_invalid_date_is_friendly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = make_vault(tmp_path)

    result = main(
        [
            "--vault-root",
            str(vault),
            "capture",
            "Bad date task",
            "--summary",
            "Exercise invalid date handling.",
            "--due",
            "tomorrow",
        ]
    )

    assert result == 1
    captured = capsys.readouterr()
    assert "Invalid date: tomorrow" in captured.err
    assert "Use YYYY-MM-DD" in captured.err


def test_cli_doctor_human_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = make_vault(tmp_path)
    monkeypatch.setattr(cli, "_load_rich_bundle", lambda: None)

    assert main(["--vault-root", str(vault), "doctor"]) == 0
    output = capsys.readouterr().out
    assert "Obsidian Legion Doctor" in output
    assert "Vault:" in output
    assert "MCP smoke test" in output


def test_cli_doctor_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = make_vault(tmp_path)

    assert main(["--vault-root", str(vault), "doctor", "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert "summary" in report
    assert "checks" in report
    assert report["paths"]["vault_root"] == str(vault.resolve())


def test_cli_list_falls_back_without_rich(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = make_vault(tmp_path)
    monkeypatch.setattr(cli, "_load_rich_bundle", lambda: None)

    assert main(["--vault-root", str(vault), "capture", "Fallback task", "--summary", "No rich installed."]) == 0
    capsys.readouterr()

    assert main(["--vault-root", str(vault), "list"]) == 0
    output = capsys.readouterr().out
    assert " | " in output
    assert "Fallback task" in output


def test_cli_list_uses_rich_table_when_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = make_vault(tmp_path)
    monkeypatch.setattr(cli, "_load_rich_bundle", fake_rich_bundle)

    assert main(["--vault-root", str(vault), "capture", "Rich task", "--summary", "Rich table output."]) == 0
    capsys.readouterr()

    assert main(["--vault-root", str(vault), "list"]) == 0
    output = capsys.readouterr().out
    assert "FAKE_RICH_TABLE" in output
    assert "Task | Status | Priority | Assignee | Due | Title" in output
    assert "Rich task" in output
