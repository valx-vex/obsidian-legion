from __future__ import annotations

from pathlib import Path

from obsidian_legion.vaultgraph.exclusion import (
    EXCLUDED_SEGMENTS,
    HARD_PRIVATE_SEGMENT,
    ExclusionEngine,
)


def make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    return vault


def test_nested_murphy_private_excluded_and_hard(tmp_path: Path) -> None:
    eng = ExclusionEngine(make_vault(tmp_path))
    nested = Path("a/b/.murphy_private/x.md")
    assert eng.is_excluded(nested) is True
    assert eng.is_hard_private(nested) is True
    # root-level private too
    assert eng.is_hard_private(Path(".murphy_private/secret.md")) is True
    # an ordinary note is neither
    assert eng.is_excluded(Path("a/b/note.md")) is False
    assert eng.is_hard_private(Path("a/b/note.md")) is False


def test_reserved_segments_component_wise(tmp_path: Path) -> None:
    eng = ExclusionEngine(make_vault(tmp_path))
    for seg in (".git", ".github", ".obsidian", ".legion", "node_modules",
                "__pycache__", ".venv", ".trash", ".crystl", ".claude"):
        assert eng.is_excluded(Path(f"deep/nested/{seg}/file.md")) is True
    assert HARD_PRIVATE_SEGMENT in EXCLUDED_SEGMENTS


def test_wiki_excluded_top_level_only(tmp_path: Path) -> None:
    eng = ExclusionEngine(make_vault(tmp_path))
    assert eng.is_excluded(Path("wiki/index.md")) is True
    assert eng.is_excluded(Path("wiki/topics/x.md")) is True
    # a deeper folder literally named "wiki" is real content — kept
    assert eng.is_excluded(Path("notes/wiki/deep.md")) is False


def test_custom_wiki_dirname(tmp_path: Path) -> None:
    eng = ExclusionEngine(make_vault(tmp_path), wiki_dirname="VEXPEDIA")
    assert eng.is_excluded(Path("VEXPEDIA/index.md")) is True
    # the default name is no longer special when overridden
    assert eng.is_excluded(Path("wiki/index.md")) is False


def test_extra_segments(tmp_path: Path) -> None:
    eng = ExclusionEngine(make_vault(tmp_path), extra_segments=frozenset({"drafts"}))
    assert eng.is_excluded(Path("stuff/drafts/wip.md")) is True
    assert eng.is_excluded(Path("stuff/keep/wip.md")) is False


def test_venv_heuristic_site_packages(tmp_path: Path) -> None:
    eng = ExclusionEngine(make_vault(tmp_path))
    assert eng.is_excluded(
        Path("mcp-venv/lib/python3.11/site-packages/pkg/readme.md")) is True


def test_venv_heuristic_pyvenv_cfg(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    # a venv dir the literal segment list would miss: name "mcp-venv"
    venv = vault / "mcp-venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    (venv / "notes.md").write_text("junk", encoding="utf-8")
    eng = ExclusionEngine(vault)
    assert eng.is_excluded(Path("mcp-venv/notes.md")) is True
    assert eng.is_excluded(Path("realnotes/notes.md")) is False


def test_iter_notes_sorted_and_filtered(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    (vault / "z.md").write_text("z", encoding="utf-8")
    (vault / "a").mkdir()
    (vault / "a" / "m.md").write_text("m", encoding="utf-8")
    (vault / "a" / "b" / ".murphy_private").mkdir(parents=True)
    (vault / "a" / "b" / ".murphy_private" / "x.md").write_text("secret", encoding="utf-8")
    (vault / "node_modules").mkdir()
    (vault / "node_modules" / "dep.md").write_text("dep", encoding="utf-8")
    (vault / "wiki").mkdir()
    (vault / "wiki" / "index.md").write_text("wiki", encoding="utf-8")
    venv = vault / "mcp-venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    (venv / "lib.md").write_text("lib", encoding="utf-8")
    (vault / "a" / "note.txt").write_text("txt", encoding="utf-8")  # non-md ignored

    eng = ExclusionEngine(vault)
    notes = list(eng.iter_notes())
    assert notes == [Path("a/m.md"), Path("z.md")]
    assert notes == sorted(notes)
    assert all(".murphy_private" not in n.parts for n in notes)
