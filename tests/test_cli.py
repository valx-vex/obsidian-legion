from __future__ import annotations

from pathlib import Path

from obsidian_legion.cli import main


def make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "06-daily" / "action-points").mkdir(parents=True)
    return vault


def test_cli_capture_and_done(tmp_path: Path, capsys) -> None:
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
    task_id = next(line.split()[1] for line in output.splitlines() if line.startswith("Created TASK-"))

    assert main(["--vault-root", str(vault), "done", task_id]) == 0
    done_output = capsys.readouterr().out
    assert f"Completed {task_id}" in done_output
