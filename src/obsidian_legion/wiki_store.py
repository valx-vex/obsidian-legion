from __future__ import annotations

import fnmatch
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import LegionPaths
from .wiki_compiler import CompilationResult, WikiCompiler
from .wiki_models import (
    WikiArticle,
    WikiManifest,
    _type_to_dir,
    file_hash,
    parse_article,
)


class WikiStore:
    def __init__(self, paths: LegionPaths, compiler: WikiCompiler | None = None):
        self.paths = paths
        self.compiler = compiler or WikiCompiler.from_config(paths.wiki_config)

    def bootstrap(self) -> list[Path]:
        self.paths.ensure_wiki_layout()
        created: list[Path] = []

        for path, content in [
            (self.paths.wiki_index, _seed_index()),
            (self.paths.wiki_log, _seed_log()),
            (self.paths.wiki_state, _seed_state()),
        ]:
            if not path.exists():
                _write_atomic(path, content)
                created.append(path)

        if not self.paths.wiki_manifest.exists():
            WikiManifest().save(self.paths.wiki_manifest)
            created.append(self.paths.wiki_manifest)

        wikiignore_path = self.paths.vault_root / ".wikiignore"
        if not wikiignore_path.exists():
            _write_atomic(
                wikiignore_path,
                "# .wikiignore — files matching these patterns are excluded from public wiki\n"
                "# Syntax: same as .gitignore (glob patterns)\n"
                "# Example:\n"
                "# raw/private-*\n"
                "# wiki/entities/personal-*\n",
            )
            created.append(wikiignore_path)

        return created

    def ingest(self, raw_path: Path) -> list[WikiArticle]:
        if not raw_path.exists():
            raise FileNotFoundError(f"Raw file not found: {raw_path}")

        manifest = WikiManifest.load(self.paths.wiki_manifest)
        content_hash = file_hash(raw_path)

        if manifest.is_ingested(raw_path) and not manifest.needs_update(raw_path):
            return []

        raw_content = raw_path.read_text(encoding="utf-8")
        index_content = ""
        if self.paths.wiki_index.exists():
            index_content = self.paths.wiki_index.read_text(encoding="utf-8")

        result = self.compiler.compile_source(
            raw_content=raw_content,
            existing_index=index_content,
            source_path=str(raw_path.relative_to(self.paths.vault_root))
            if _is_relative_to(raw_path, self.paths.vault_root)
            else str(raw_path),
        )

        written_articles = self._write_articles(result.articles)
        self._rebuild_index()
        self._append_log(result.log_entry)
        self._update_state()

        page_ids = [article.article_id for article in written_articles]
        manifest.record(raw_path, content_hash, page_ids)
        manifest.save(self.paths.wiki_manifest)

        return written_articles

    def compile_all(self, dry_run: bool = False) -> list[WikiArticle]:
        self.bootstrap()
        manifest = WikiManifest.load(self.paths.wiki_manifest)
        pending = self._find_pending(manifest)

        if dry_run:
            for path in pending:
                print(f"Would compile: {path}")
            return []

        all_articles: list[WikiArticle] = []
        for raw_path in pending:
            articles = self.ingest(raw_path)
            all_articles.extend(articles)

        return all_articles

    def compile_vault(
        self,
        scan_dirs: list[Path] | None = None,
        dry_run: bool = False,
    ) -> list[WikiArticle]:
        """Scan the entire vault (or specific directories) for .md files and compile them.

        By default scans vault_root for all .md files, excluding wiki/, .obsidian/,
        .git/, node_modules/, .venv/, and __pycache__/ directories.
        Uses the same manifest tracking as compile_all (skip already-ingested, detect changes by hash).
        """
        self.bootstrap()
        manifest = WikiManifest.load(self.paths.wiki_manifest)
        pending = self._find_vault_pending(manifest, scan_dirs)

        if dry_run:
            for path in pending:
                print(f"Would compile: {path}")
            return []

        all_articles: list[WikiArticle] = []
        for vault_path in pending:
            articles = self.ingest(vault_path)
            all_articles.extend(articles)

        return all_articles

    def _load_wikiignore(self) -> list[str]:
        ignore_path = self.paths.vault_root / ".wikiignore"
        if not ignore_path.exists():
            return []
        return [
            line.strip()
            for line in ignore_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]

    def _is_ignored(self, path: Path, patterns: list[str]) -> bool:
        try:
            relative = str(path.relative_to(self.paths.vault_root))
        except ValueError:
            return False
        return any(
            fnmatch.fnmatch(relative, pat) or fnmatch.fnmatch(path.name, pat)
            for pat in patterns
        )

    def compile_public(self, dry_run: bool = False) -> list[WikiArticle]:
        """Compile only non-ignored files into wiki-public/."""
        self.bootstrap()
        self.paths.wiki_public_root.mkdir(parents=True, exist_ok=True)
        patterns = self._load_wikiignore()
        manifest = WikiManifest.load(self.paths.wiki_manifest)

        # Get pending files, filter out ignored
        pending = self._find_pending(manifest)
        if patterns:
            pending = [p for p in pending if not self._is_ignored(p, patterns)]

        if dry_run:
            for p in pending:
                print(f"Would compile (public): {p}")
            return []

        articles: list[WikiArticle] = []
        for raw_path in pending:
            result_articles = self.ingest(raw_path)
            articles.extend(result_articles)

        # Copy non-ignored articles to wiki-public/
        self._sync_public_wiki(patterns)
        return articles

    def _sync_public_wiki(self, patterns: list[str]) -> None:
        """Copy non-ignored wiki articles to wiki-public/."""
        public = self.paths.wiki_public_root
        public.mkdir(parents=True, exist_ok=True)
        for subdir_name in ["entities", "topics", "sources"]:
            src = self.paths.wiki_root / subdir_name
            dst = public / subdir_name
            dst.mkdir(parents=True, exist_ok=True)
            if not src.exists():
                continue
            for md in src.rglob("*.md"):
                if not self._is_ignored(md, patterns):
                    shutil.copy2(md, dst / md.name)
        # Copy index, state (not log — internal)
        for f in ["index.md", "state.md"]:
            src_f = self.paths.wiki_root / f
            if src_f.exists():
                shutil.copy2(src_f, public / f)

    def export_public(self, output_dir: Path) -> list[Path]:
        """Export public wiki to an external directory."""
        patterns = self._load_wikiignore()
        self._sync_public_wiki(patterns)
        output_dir.mkdir(parents=True, exist_ok=True)
        exported: list[Path] = []
        for item in self.paths.wiki_public_root.rglob("*.md"):
            dest = output_dir / item.relative_to(self.paths.wiki_public_root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            exported.append(dest)
        return exported

    def search(self, query: str, limit: int = 10, deep: bool = False) -> list[WikiArticle]:
        query_lower = query.lower()
        scored: list[tuple[int, WikiArticle]] = []

        for article in self.load_articles():
            score = 0
            if query_lower in article.title.lower():
                score += 10
            if query_lower in article.summary.lower():
                score += 5
            if any(query_lower in tag.lower() for tag in article.tags):
                score += 3
            if query_lower in article.content.lower():
                score += 1
            if score > 0:
                scored.append((score, article))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        text_results = [article for _, article in scored[:limit]]

        if deep and len(text_results) < limit:
            qdrant_results = self._qdrant_search(query, limit=limit - len(text_results))
            # Deduplicate by article_id
            seen_ids = {a.article_id for a in text_results}
            for article in qdrant_results:
                if article.article_id not in seen_ids:
                    text_results.append(article)
                    seen_ids.add(article.article_id)
                    if len(text_results) >= limit:
                        break

        return text_results

    def _qdrant_search(self, query: str, limit: int = 10) -> list[WikiArticle]:
        """Search Qdrant vector store. Returns empty list if Qdrant is unavailable."""
        try:
            import httpx
        except ImportError:
            return []

        # Generate embedding via Ollama
        try:
            embed_resp = httpx.post(
                "http://localhost:11434/api/embed",
                json={"model": "nomic-embed-text", "input": query},
                timeout=30.0,
            )
            embed_resp.raise_for_status()
            embedding = embed_resp.json().get("embeddings", [[]])[0]
            if not embedding:
                return []
        except Exception:
            return []

        # Query Qdrant
        try:
            qdrant_resp = httpx.post(
                f"{self.paths.qdrant_url}/collections/{self.paths.qdrant_collection}/points/search",
                json={
                    "vector": embedding,
                    "limit": limit,
                    "with_payload": True,
                },
                timeout=10.0,
            )
            qdrant_resp.raise_for_status()
            results = qdrant_resp.json().get("result", [])
        except Exception:
            return []

        articles: list[WikiArticle] = []
        now = datetime.now().astimezone()
        for hit in results:
            payload = hit.get("payload", {})
            title = payload.get("title", "Untitled")
            from .wiki_models import slugify
            articles.append(WikiArticle(
                article_id=slugify(title),
                title=title,
                article_type=payload.get("type", "topic"),
                summary=payload.get("summary", ""),
                content=payload.get("content_preview", payload.get("content", "")),
                tags=payload.get("tags", []),
                backlinks=[],
                source_files=[payload.get("path", "")] if payload.get("path") else [],
                created_at=now,
                updated_at=now,
                path=Path(payload["path"]) if payload.get("path") else None,
            ))
        return articles

    def status(self) -> dict[str, Any]:
        manifest = WikiManifest.load(self.paths.wiki_manifest)
        raw_files = list(self.paths.raw_root.rglob("*.md")) if self.paths.raw_root.exists() else []
        pending = self._find_pending(manifest)
        articles = self.load_articles()

        return {
            "raw_files": len(raw_files),
            "ingested": len(manifest.entries),
            "pending": len(pending),
            "articles": len(articles),
            "entities": sum(1 for a in articles if a.article_type == "entity"),
            "topics": sum(1 for a in articles if a.article_type == "topic"),
            "sources": sum(1 for a in articles if a.article_type == "source"),
            "wiki_root": str(self.paths.wiki_root),
            "raw_root": str(self.paths.raw_root),
        }

    def list_articles(self, article_type: str | None = None) -> list[WikiArticle]:
        articles = self.load_articles()
        if article_type:
            articles = [a for a in articles if a.article_type == article_type]
        return sorted(articles, key=lambda a: a.title)

    def get_article(self, article_id: str) -> WikiArticle:
        for article in self.load_articles():
            if article.article_id == article_id:
                return article
        raise KeyError(f"Article not found: {article_id}")

    def load_articles(self) -> list[WikiArticle]:
        articles: list[WikiArticle] = []
        for subdir in [self.paths.wiki_entities, self.paths.wiki_topics, self.paths.wiki_sources]:
            if not subdir.exists():
                continue
            for path in sorted(subdir.rglob("*.md")):
                article = parse_article(path)
                if article is not None:
                    articles.append(article)
        return articles

    def _find_pending(self, manifest: WikiManifest) -> list[Path]:
        if not self.paths.raw_root.exists():
            return []
        pending: list[Path] = []
        for raw_path in sorted(self.paths.raw_root.rglob("*.md")):
            if manifest.needs_update(raw_path):
                pending.append(raw_path)
        return pending

    _VAULT_SCAN_EXCLUDES = {"wiki", ".obsidian", ".git", "node_modules", ".venv", "__pycache__"}

    def _find_vault_pending(
        self,
        manifest: WikiManifest,
        scan_dirs: list[Path] | None = None,
    ) -> list[Path]:
        roots = scan_dirs if scan_dirs else [self.paths.vault_root]
        pending: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            for md_path in sorted(root.rglob("*.md")):
                # Exclude directories that should not be scanned
                rel_parts = set(md_path.relative_to(self.paths.vault_root).parts) if _is_relative_to(md_path, self.paths.vault_root) else set()
                if rel_parts & self._VAULT_SCAN_EXCLUDES:
                    continue
                if manifest.needs_update(md_path):
                    pending.append(md_path)
        return pending

    def _write_articles(self, articles: list[WikiArticle]) -> list[WikiArticle]:
        written: list[WikiArticle] = []
        for article in articles:
            try:
                article.validate()
            except ValueError:
                article.article_type = "topic"

            type_dir = _type_to_dir(article.article_type)
            dest = self.paths.wiki_root / type_dir / f"{article.article_id}.md"
            dest.parent.mkdir(parents=True, exist_ok=True)
            article.path = dest
            _write_atomic(dest, article.to_markdown())
            written.append(article)
        return written

    def _rebuild_index(self) -> None:
        articles = self.load_articles()
        lines = [
            "# Wiki Index",
            "",
            f"_Last updated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')}_",
            "",
        ]

        by_type: dict[str, list[WikiArticle]] = {"entity": [], "topic": [], "source": []}
        for article in articles:
            by_type.setdefault(article.article_type, []).append(article)

        for label, type_key in [("Entities", "entity"), ("Topics", "topic"), ("Sources", "source")]:
            items = sorted(by_type.get(type_key, []), key=lambda a: a.title)
            if items:
                lines.append(f"## {label}")
                lines.append("")
                for article in items:
                    lines.append(article.index_line())
                lines.append("")

        _write_atomic(self.paths.wiki_index, "\n".join(lines) + "\n")

    def _append_log(self, entry: str) -> None:
        now = datetime.now().astimezone()
        line = f"## [{now.strftime('%Y-%m-%d')}] {entry}\n"
        if self.paths.wiki_log.exists():
            existing = self.paths.wiki_log.read_text(encoding="utf-8")
        else:
            existing = "# Wiki Log\n\n"
        _write_atomic(self.paths.wiki_log, existing + "\n" + line)
        self._compact_log()

    def _update_state(self) -> None:
        articles = self.load_articles()
        manifest = WikiManifest.load(self.paths.wiki_manifest)
        now = datetime.now().astimezone()
        content = "\n".join([
            "# Wiki State",
            "",
            f"Updated: {now.isoformat()}",
            f"Articles: {len(articles)}",
            f"Entities: {sum(1 for a in articles if a.article_type == 'entity')}",
            f"Topics: {sum(1 for a in articles if a.article_type == 'topic')}",
            f"Sources: {sum(1 for a in articles if a.article_type == 'source')}",
            f"Raw files ingested: {len(manifest.entries)}",
            "",
        ])
        _write_atomic(self.paths.wiki_state, content)

    def _compact_log(self, max_lines: int = 60) -> None:
        if not self.paths.wiki_log.exists():
            return
        lines = self.paths.wiki_log.read_text(encoding="utf-8").splitlines()
        if len(lines) <= max_lines:
            return
        header = lines[:3]
        entries = lines[3:]
        keep = entries[-(max_lines - 5) :]
        compacted = header + ["", "_Older entries compacted._", ""] + keep
        _write_atomic(self.paths.wiki_log, "\n".join(compacted) + "\n")


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=path.parent
    ) as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _seed_index() -> str:
    return "# Wiki Index\n\n_No articles yet. Run `obsidian-legion wiki compile` to populate._\n"


def _seed_log() -> str:
    now = datetime.now().astimezone()
    return f"# Wiki Log\n\n## [{now.strftime('%Y-%m-%d')}] init | Wiki bootstrapped\n"


def _seed_state() -> str:
    now = datetime.now().astimezone()
    return f"# Wiki State\n\nUpdated: {now.isoformat()}\nArticles: 0\nRaw files ingested: 0\n"
