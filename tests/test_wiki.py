from __future__ import annotations

from datetime import datetime
from pathlib import Path

from obsidian_legion.config import LegionPaths
from obsidian_legion.wiki_compiler import CompilationResult, WikiCompiler
from obsidian_legion.wiki_models import WikiArticle, WikiManifest, file_hash
from obsidian_legion.wiki_store import WikiStore


def make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "06-daily" / "action-points").mkdir(parents=True)
    return vault


def make_raw_file(vault: Path, name: str, content: str) -> Path:
    raw_dir = vault / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / name
    raw_path.write_text(content, encoding="utf-8")
    return raw_path


class MockCompiler(WikiCompiler):
    """Deterministic compiler that returns predictable results without LLM calls."""

    def __init__(self) -> None:
        super().__init__(provider="mock", model="mock")

    def compile_source(
        self, raw_content: str, existing_index: str, source_path: str = ""
    ) -> CompilationResult:
        title = source_path.replace("raw/", "").replace(".md", "").replace("-", " ").title()
        now = datetime.now().astimezone()
        article = WikiArticle(
            article_id=title.lower().replace(" ", "-"),
            title=title,
            article_type="topic",
            summary=f"Summary of {title}",
            content=f"Compiled content from {source_path}.\n\n{raw_content[:200]}",
            tags=["test", "compiled"],
            backlinks=[],
            source_files=[source_path],
            created_at=now,
            updated_at=now,
        )
        return CompilationResult(
            articles=[article],
            log_entry=f"Compiled {source_path} -> 1 article",
        )


def test_wiki_bootstrap(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())

    created = wiki.bootstrap()
    assert len(created) > 0
    assert paths.wiki_index.exists()
    assert paths.wiki_log.exists()
    assert paths.wiki_state.exists()
    assert paths.wiki_manifest.exists()
    assert paths.wiki_entities.is_dir()
    assert paths.wiki_topics.is_dir()
    assert paths.wiki_sources.is_dir()
    assert paths.raw_root.is_dir()


def test_wiki_bootstrap_idempotent(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())

    wiki.bootstrap()
    second = wiki.bootstrap()
    assert second == []


def test_wiki_ingest(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())
    wiki.bootstrap()

    raw_path = make_raw_file(vault, "2026-04-16-test.md", "# Test\nSome content about testing.")
    articles = wiki.ingest(raw_path)

    assert len(articles) == 1
    assert articles[0].article_type == "topic"
    assert articles[0].path is not None
    assert articles[0].path.exists()

    index = paths.wiki_index.read_text(encoding="utf-8")
    assert articles[0].title in index

    log = paths.wiki_log.read_text(encoding="utf-8")
    assert "Compiled" in log

    manifest = WikiManifest.load(paths.wiki_manifest)
    assert manifest.is_ingested(raw_path)


def test_wiki_ingest_idempotent(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())
    wiki.bootstrap()

    raw_path = make_raw_file(vault, "2026-04-16-test.md", "# Test\nContent.")
    wiki.ingest(raw_path)
    second = wiki.ingest(raw_path)
    assert second == []


def test_wiki_ingest_updated_file(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())
    wiki.bootstrap()

    raw_path = make_raw_file(vault, "evolving.md", "Version 1")
    wiki.ingest(raw_path)

    raw_path.write_text("Version 2 with new content", encoding="utf-8")
    articles = wiki.ingest(raw_path)
    assert len(articles) == 1


def test_wiki_compile_all(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())
    wiki.bootstrap()

    make_raw_file(vault, "file-a.md", "Content A")
    make_raw_file(vault, "file-b.md", "Content B")
    make_raw_file(vault, "file-c.md", "Content C")

    articles = wiki.compile_all()
    assert len(articles) == 3


def test_wiki_compile_all_skips_ingested(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())
    wiki.bootstrap()

    make_raw_file(vault, "already.md", "Already ingested")
    wiki.compile_all()

    make_raw_file(vault, "new.md", "New content")
    articles = wiki.compile_all()
    assert len(articles) == 1


def test_wiki_compile_dry_run(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())
    wiki.bootstrap()

    make_raw_file(vault, "pending.md", "Pending content")
    articles = wiki.compile_all(dry_run=True)
    assert articles == []

    manifest = WikiManifest.load(paths.wiki_manifest)
    assert len(manifest.entries) == 0


def test_wiki_search(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())
    wiki.bootstrap()

    make_raw_file(vault, "consciousness.md", "Deep consciousness research")
    wiki.compile_all()

    results = wiki.search("consciousness")
    assert len(results) >= 1
    assert any("consciousness" in r.article_id.lower() or "consciousness" in r.content.lower() for r in results)


def test_wiki_search_no_results(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())
    wiki.bootstrap()

    results = wiki.search("nonexistent")
    assert results == []


def test_wiki_status(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())
    wiki.bootstrap()

    make_raw_file(vault, "one.md", "Content one")
    make_raw_file(vault, "two.md", "Content two")
    wiki.ingest(vault / "raw" / "one.md")

    status = wiki.status()
    assert status["raw_files"] == 2
    assert status["ingested"] == 1
    assert status["pending"] == 1
    assert status["articles"] >= 1


def test_wiki_list_articles(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())
    wiki.bootstrap()

    make_raw_file(vault, "alpha.md", "Alpha")
    make_raw_file(vault, "beta.md", "Beta")
    wiki.compile_all()

    all_articles = wiki.list_articles()
    assert len(all_articles) == 2

    topics = wiki.list_articles(article_type="topic")
    assert len(topics) == 2

    entities = wiki.list_articles(article_type="entity")
    assert len(entities) == 0


def test_wiki_get_article(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())
    wiki.bootstrap()

    make_raw_file(vault, "target.md", "Target content")
    articles = wiki.compile_all()
    article_id = articles[0].article_id

    found = wiki.get_article(article_id)
    assert found.article_id == article_id


def test_wiki_manifest_persistence(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)

    manifest = WikiManifest()
    raw_path = make_raw_file(vault, "test.md", "Test content")
    manifest.record(raw_path, file_hash(raw_path), ["test-article"])
    manifest.save(paths.wiki_manifest)

    loaded = WikiManifest.load(paths.wiki_manifest)
    assert loaded.is_ingested(raw_path)
    assert not loaded.needs_update(raw_path)


def test_wiki_log_compaction(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    paths = LegionPaths.discover(vault)
    wiki = WikiStore(paths, compiler=MockCompiler())
    wiki.bootstrap()

    for i in range(70):
        make_raw_file(vault, f"file-{i:03d}.md", f"Content {i}")
    wiki.compile_all()

    log_text = paths.wiki_log.read_text(encoding="utf-8")
    lines = log_text.strip().splitlines()
    assert len(lines) <= 65
