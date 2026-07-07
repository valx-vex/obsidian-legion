import json
from pathlib import Path

import pytest

from obsidian_legion.vaultgraph import registry as reg


def test_register_and_load(tmp_path):
    rpath = tmp_path / "vaults.json"
    reg.register_vault("exegesis", tmp_path / "ex", path=rpath)
    reg.register_vault("prime", tmp_path / "pr", path=rpath)
    data = reg.load_registry(rpath)
    assert set(data) == {"exegesis", "prime"}
    assert data["exegesis"] == (tmp_path / "ex").resolve()


def test_default_is_first(tmp_path):
    rpath = tmp_path / "vaults.json"
    reg.register_vault("first", tmp_path / "a", path=rpath)
    reg.register_vault("second", tmp_path / "b", path=rpath)
    name, root = reg.default_vault(rpath)
    assert name == "first"
    assert root == (tmp_path / "a").resolve()


def test_load_missing_returns_empty(tmp_path):
    assert reg.load_registry(tmp_path / "nope.json") == {}


def test_default_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        reg.default_vault(tmp_path / "nope.json")


from obsidian_legion.config import (
    LegionPaths,
    _looks_like_vault,
    _looks_like_vault_root,
)


def test_root_only_accepts_obsidian_only(tmp_path, monkeypatch):
    monkeypatch.delenv("OBSIDIAN_LEGION_VAULT", raising=False)
    vault = tmp_path / "v"
    (vault / ".obsidian").mkdir(parents=True)
    assert _looks_like_vault_root(vault) is True
    assert _looks_like_vault(vault) is False
    # explicit --vault-root resolution now trusts .obsidian alone (root-only)
    paths = LegionPaths.discover(vault)
    assert paths.vault_root == vault.resolve()


def test_strict_cwd_walk_requires_task_layout(tmp_path, monkeypatch):
    monkeypatch.delenv("OBSIDIAN_LEGION_VAULT", raising=False)
    vault = tmp_path / "v"
    (vault / ".obsidian").mkdir(parents=True)
    monkeypatch.chdir(vault)
    with pytest.raises(FileNotFoundError):
        LegionPaths.discover(strict=True)      # implicit walk still needs action-points
    paths = LegionPaths.discover(strict=False)  # root-only walk finds the .obsidian vault
    assert paths.vault_root == vault.resolve()


from obsidian_legion import cli
from obsidian_legion.cli import main


def _make_graph_vault(tmp_path):
    vault = tmp_path / "gv"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "apple.md").write_text("# Apple\n[[banana]] #fruit\n", encoding="utf-8")
    (vault / "banana.md").write_text("# Banana\n[[apple]] #fruit\n", encoding="utf-8")
    return vault


def test_graph_build_status_query(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("OBSIDIAN_LEGION_VAULT", raising=False)
    monkeypatch.setattr(cli, "_load_rich_bundle", lambda: None)
    vault = _make_graph_vault(tmp_path)

    assert main(["graph", "build", "--vault", str(vault), "--skip-embeddings"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["notes_seen"] == 2
    assert report["qdrant_ok"] is False

    assert main(["graph", "status", "--vault", str(vault)]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert isinstance(stats, dict)

    assert main(["graph", "query", "--vault", str(vault), "--search", "Apple"]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert isinstance(hits, list)


def test_graph_status_not_built(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("OBSIDIAN_LEGION_VAULT", raising=False)
    monkeypatch.setattr(cli, "_load_rich_bundle", lambda: None)
    vault = tmp_path / "gv"
    (vault / ".obsidian").mkdir(parents=True)
    assert main(["graph", "status", "--vault", str(vault)]) == 1
    assert "Graph not built yet" in capsys.readouterr().err


def test_graph_unknown_vault(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("OBSIDIAN_LEGION_VAULT", raising=False)
    monkeypatch.setattr(cli, "_load_rich_bundle", lambda: None)
    monkeypatch.setattr(reg, "load_registry", lambda *a, **k: {})
    assert main(["graph", "status", "--vault", "no-such-vault-xyz"]) == 1
    assert "Unknown vault" in capsys.readouterr().err


def test_graph_uses_registry_default(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("OBSIDIAN_LEGION_VAULT", raising=False)
    monkeypatch.setattr(cli, "_load_rich_bundle", lambda: None)
    vault = _make_graph_vault(tmp_path)
    monkeypatch.setattr(reg, "default_vault", lambda *a, **k: ("gv", vault))
    assert main(["graph", "build", "--skip-embeddings"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["notes_seen"] == 2


def test_wiki_reset_wiring(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("OBSIDIAN_LEGION_VAULT", raising=False)
    monkeypatch.setattr(cli, "_load_rich_bundle", lambda: None)
    vault = tmp_path / "gv"
    (vault / ".obsidian").mkdir(parents=True)
    calls = {}

    class FakeWriter:
        def reset(self, regenerate=False):
            calls["regenerate"] = regenerate
            return {"removed": 3, "regenerated": 0}

    monkeypatch.setattr(cli, "_build_wiki_writer", lambda root: FakeWriter())
    assert main(["--vault-root", str(vault), "wiki", "reset", "--regenerate"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["removed"] == 3
    assert calls["regenerate"] is True
