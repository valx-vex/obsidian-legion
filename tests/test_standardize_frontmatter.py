from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

# Allow import from scripts/ without install
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from standardize_frontmatter import (
    CANONICAL_FIELDS,
    infer_area,
    infer_project,
    infer_type,
    parse_frontmatter,
    process_file,
    run,
    serialize_frontmatter,
    title_from_filename,
    walk_vault,
)


# ── helpers ────────────────────────────────────────────────────────


def _make_vault(tmp_path: Path) -> Path:
    """Create a minimal vault directory tree for testing."""
    vault = tmp_path / "vault"
    vault.mkdir()
    for d in (
        "01-consciousness",
        "02-books",
        "03-code/active/my-project",
        "06-daily",
        "08-publishing",
        "09-archive",
        ".obsidian",
        ".git",
        "wiki",
        "node_modules",
        "raw",
    ):
        (vault / d).mkdir(parents=True, exist_ok=True)
    return vault


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


# ── parse_frontmatter ──────────────────────────────────────────────


class TestParseFrontmatter:
    def test_no_frontmatter(self) -> None:
        meta, body = parse_frontmatter("# Hello world\n\nSome content.\n")
        assert meta is None
        assert body.startswith("# Hello world")

    def test_valid_frontmatter(self) -> None:
        text = "---\ntitle: Test\nstatus: active\n---\n# Body\n"
        meta, body = parse_frontmatter(text)
        assert meta is not None
        assert meta["title"] == "Test"
        assert meta["status"] == "active"
        assert body == "# Body\n"

    def test_empty_frontmatter(self) -> None:
        text = "---\n---\n# Body\n"
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == "# Body\n"

    def test_malformed_yaml_returns_none(self) -> None:
        text = "---\n: : bad yaml [[\n---\n# Body\n"
        meta, body = parse_frontmatter(text)
        # Malformed is treated as no frontmatter
        assert meta is None

    def test_preserves_crlf_normalization(self) -> None:
        text = "---\r\ntitle: Win\r\n---\r\n# Body\r\n"
        meta, body = parse_frontmatter(text)
        assert meta is not None
        assert meta["title"] == "Win"


# ── serialize_frontmatter ──────────────────────────────────────────


class TestSerializeFrontmatter:
    def test_round_trip(self) -> None:
        data = {"title": "Round Trip", "status": "active", "tags": ["a", "b"]}
        serialized = serialize_frontmatter(data)
        assert serialized.startswith("---\n")
        assert serialized.endswith("---\n")
        parsed, _ = parse_frontmatter(serialized + "\n# body\n")
        assert parsed is not None
        assert parsed["title"] == "Round Trip"
        assert parsed["tags"] == ["a", "b"]


# ── inference helpers ──────────────────────────────────────────────


class TestInferType:
    @pytest.mark.parametrize(
        "rel, expected",
        [
            ("01-consciousness/notes/idea.md", "research"),
            ("02-books/fiction/novel.md", "source"),
            ("03-code/active/proj/README.md", "project"),
            ("04-work/meetings/standup.md", "operations"),
            ("05-vexnet/nodes/node.md", "project"),
            ("06-daily/2025/log.md", "daily"),
            ("08-publishing/drafts/ch1.md", "writing"),
            ("09-archive/old/note.md", "archive"),
            ("random/file.md", "note"),
        ],
    )
    def test_dir_type_mapping(self, rel: str, expected: str) -> None:
        assert infer_type(Path(rel)) == expected


class TestInferProject:
    def test_deep_path(self) -> None:
        assert infer_project(Path("03-code/active/my-project/README.md")) == "my-project"

    def test_shallow_path(self) -> None:
        # Only top-level + filename: not enough depth to infer project
        assert infer_project(Path("03-code/README.md")) is None


class TestInferArea:
    def test_returns_top_level(self) -> None:
        assert infer_area(Path("03-code/active/proj/file.md")) == "03-code"

    def test_empty_path(self) -> None:
        assert infer_area(Path("file.md")) == "file.md"


class TestTitleFromFilename:
    def test_simple(self) -> None:
        assert title_from_filename(Path("My_Cool_Note.md")) == "My Cool Note"

    def test_date_prefix_stripped(self) -> None:
        assert title_from_filename(Path("2025-04-16_daily-log.md")) == "daily log"

    def test_compact_date_stripped(self) -> None:
        assert title_from_filename(Path("20250416_standup.md")) == "standup"


# ── walk_vault ─────────────────────────────────────────────────────


class TestWalkVault:
    def test_excludes_hidden_dirs(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write(vault / "01-consciousness" / "note.md", "# Visible\n")
        _write(vault / ".obsidian" / "config.md", "# Hidden\n")
        _write(vault / ".git" / "HEAD.md", "# Git\n")
        _write(vault / "wiki" / "article.md", "# Wiki\n")
        _write(vault / "node_modules" / "pkg.md", "# NPM\n")
        _write(vault / "raw" / "dump.md", "# Raw\n")

        files = walk_vault(vault)
        names = {f.name for f in files}
        assert "note.md" in names
        assert "config.md" not in names
        assert "HEAD.md" not in names
        assert "article.md" not in names
        assert "pkg.md" not in names
        assert "dump.md" not in names

    def test_subdir_filter(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write(vault / "01-consciousness" / "a.md", "# A\n")
        _write(vault / "02-books" / "b.md", "# B\n")

        files = walk_vault(vault, subdir="01-consciousness")
        names = {f.name for f in files}
        assert "a.md" in names
        assert "b.md" not in names

    def test_missing_subdir_raises(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        with pytest.raises(FileNotFoundError):
            walk_vault(vault, subdir="nonexistent")


# ── process_file ───────────────────────────────────────────────────


class TestProcessFile:
    def test_no_frontmatter_dry_run(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        f = _write(vault / "01-consciousness" / "idea.md", "# An Idea\n\nContent.\n")

        result = process_file(f, vault, dry_run=True)
        assert result.status == "created"
        assert len(result.added_fields) == len(CANONICAL_FIELDS)
        # File should NOT be modified
        assert "---" not in f.read_text(encoding="utf-8")

    def test_no_frontmatter_live(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        f = _write(vault / "01-consciousness" / "idea.md", "# An Idea\n\nContent.\n")

        result = process_file(f, vault, dry_run=False)
        assert result.status == "created"

        text = f.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "# An Idea" in text
        assert "Content." in text

        meta, body = parse_frontmatter(text)
        assert meta is not None
        assert meta["type"] == "research"
        assert meta["publish"] is False
        assert meta["status"] == "active"

    def test_complete_frontmatter_unchanged(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        fm = "\n".join(
            [
                "---",
                "title: Complete",
                "type: research",
                "status: active",
                "created: '2025-01-01'",
                "updated: '2025-01-01'",
                "aliases: []",
                "tags: []",
                "project: test",
                "area: 01-consciousness",
                "source: null",
                "publish: false",
                "related: []",
                "---",
                "# Body",
                "",
            ]
        )
        f = _write(vault / "01-consciousness" / "complete.md", fm)
        original = f.read_text(encoding="utf-8")

        result = process_file(f, vault, dry_run=False)
        assert result.status == "complete"
        assert result.added_fields == []
        # File should not be rewritten at all
        assert f.read_text(encoding="utf-8") == original

    def test_partial_frontmatter_fills_missing(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        fm = "---\ntitle: Partial\nstatus: draft\n---\n# Body\n"
        f = _write(vault / "03-code" / "active" / "my-project" / "notes.md", fm)

        result = process_file(f, vault, dry_run=False)
        assert result.status == "updated"
        assert "type" in result.added_fields
        assert "title" not in result.added_fields  # was already present
        assert "status" not in result.added_fields

        meta, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
        assert meta is not None
        assert meta["title"] == "Partial"  # preserved
        assert meta["status"] == "draft"  # preserved, not overwritten
        assert meta["type"] == "project"  # inferred and added
        assert meta["publish"] is False

    def test_archive_gets_archive_status(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        f = _write(vault / "09-archive" / "old.md", "# Old stuff\n")

        process_file(f, vault, dry_run=False)
        meta, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
        assert meta is not None
        assert meta["status"] == "archive"
        assert meta["type"] == "archive"

    def test_preserves_extra_fields(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        fm = "---\ntitle: Extra\ncustom_field: hello\n---\n# Body\n"
        f = _write(vault / "01-consciousness" / "extra.md", fm)

        process_file(f, vault, dry_run=False)
        meta, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
        assert meta is not None
        assert meta["custom_field"] == "hello"
        assert "type" in meta  # canonical field added

    def test_preserves_body_content(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        body = "# Title\n\nParagraph one.\n\n## Section\n\nParagraph two.\n"
        f = _write(vault / "06-daily" / "note.md", body)

        process_file(f, vault, dry_run=False)
        text = f.read_text(encoding="utf-8")
        assert "Paragraph one." in text
        assert "## Section" in text
        assert "Paragraph two." in text


# ── run (integration) ──────────────────────────────────────────────


class TestRun:
    def test_limit(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        for i in range(5):
            _write(vault / "01-consciousness" / f"note_{i}.md", f"# Note {i}\n")

        results = run(vault, dry_run=True, limit=3)
        assert len(results) == 3

    def test_subdir_filter(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write(vault / "01-consciousness" / "a.md", "# A\n")
        _write(vault / "02-books" / "b.md", "# B\n")

        results = run(vault, dry_run=True, subdir="01-consciousness")
        paths = {r.path.name for r in results}
        assert "a.md" in paths
        assert "b.md" not in paths

    def test_full_run_modifies_files(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write(vault / "01-consciousness" / "bare.md", "# Bare\n")
        _write(
            vault / "02-books" / "partial.md",
            "---\ntitle: Has Title\n---\n# Body\n",
        )

        results = run(vault, dry_run=False)
        statuses = {r.path.name: r.status for r in results}
        assert statuses["bare.md"] == "created"
        assert statuses["partial.md"] == "updated"

        # Verify files were actually modified
        for r in results:
            text = r.path.read_text(encoding="utf-8")
            assert text.startswith("---\n")


# ── main CLI entrypoint ────────────────────────────────────────────


class TestMainCLI:
    def test_dry_run_returns_zero(self, tmp_path: Path, capsys) -> None:
        vault = _make_vault(tmp_path)
        _write(vault / "01-consciousness" / "test.md", "# Test\n")

        from standardize_frontmatter import main

        rc = main(["--vault-root", str(vault), "--dry-run", "--limit", "5"])
        assert rc == 0
        output = capsys.readouterr().out
        assert "Scanned" in output

    def test_bad_vault_returns_one(self, capsys) -> None:
        from standardize_frontmatter import main

        rc = main(["--vault-root", "/nonexistent/path/xyz"])
        assert rc == 1
