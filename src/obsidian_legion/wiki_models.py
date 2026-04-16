from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


VALID_ARTICLE_TYPES = ("entity", "topic", "source")


@dataclass(slots=True)
class WikiArticle:
    article_id: str
    title: str
    article_type: str
    summary: str
    content: str
    tags: list[str] = field(default_factory=list)
    backlinks: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now().astimezone())
    updated_at: datetime = field(default_factory=lambda: datetime.now().astimezone())
    path: Path | None = None

    def to_frontmatter(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "type": self.article_type,
            "summary": self.summary,
            "tags": self.tags,
            "backlinks": self.backlinks,
            "source_files": self.source_files,
            "created": self.created_at.strftime("%Y-%m-%d"),
            "updated": self.updated_at.strftime("%Y-%m-%d"),
        }

    def to_markdown(self) -> str:
        fm = yaml.safe_dump(
            self.to_frontmatter(), sort_keys=False, allow_unicode=True, width=100
        ).strip()
        return f"---\n{fm}\n---\n\n{self.content}\n"

    def to_dict(self) -> dict[str, Any]:
        data = self.to_frontmatter()
        data["article_id"] = self.article_id
        data["content"] = self.content
        if self.path is not None:
            data["path"] = str(self.path)
        return data

    def index_line(self) -> str:
        type_dir = _type_to_dir(self.article_type)
        return f"- [[{type_dir}/{self.article_id}|{self.title}]] -- {self.summary}"

    def validate(self) -> None:
        if self.article_type not in VALID_ARTICLE_TYPES:
            raise ValueError(f"Invalid article type: {self.article_type}")


@dataclass(slots=True)
class ManifestEntry:
    raw_path: str
    ingested_at: str
    file_hash: str
    resulting_pages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_path": self.raw_path,
            "ingested_at": self.ingested_at,
            "file_hash": self.file_hash,
            "resulting_pages": self.resulting_pages,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManifestEntry:
        return cls(
            raw_path=str(data["raw_path"]),
            ingested_at=str(data["ingested_at"]),
            file_hash=str(data["file_hash"]),
            resulting_pages=list(data.get("resulting_pages", [])),
        )


class WikiManifest:
    def __init__(self, entries: dict[str, ManifestEntry] | None = None):
        self.entries: dict[str, ManifestEntry] = entries or {}

    def is_ingested(self, raw_path: Path) -> bool:
        return str(raw_path) in self.entries

    def needs_update(self, raw_path: Path) -> bool:
        key = str(raw_path)
        if key not in self.entries:
            return True
        current_hash = file_hash(raw_path)
        return self.entries[key].file_hash != current_hash

    def record(self, raw_path: Path, content_hash: str, pages: list[str]) -> None:
        self.entries[str(raw_path)] = ManifestEntry(
            raw_path=str(raw_path),
            ingested_at=datetime.now().astimezone().isoformat(),
            file_hash=content_hash,
            resulting_pages=pages,
        )

    @classmethod
    def load(cls, path: Path) -> WikiManifest:
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = {
            key: ManifestEntry.from_dict(val) for key, val in raw.get("entries", {}).items()
        }
        return cls(entries=entries)

    def save(self, path: Path) -> None:
        data = {"entries": {key: entry.to_dict() for key, entry in self.entries.items()}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def slugify(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return value or "article"


def _type_to_dir(article_type: str) -> str:
    return {"entity": "entities", "topic": "topics", "source": "sources"}.get(
        article_type, "topics"
    )


def parse_article(path: Path) -> WikiArticle | None:
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return None
    _, _, rest = normalized.partition("\n")
    frontmatter_text, separator, body = rest.partition("\n---\n")
    if not separator:
        return None
    fm = yaml.safe_load(frontmatter_text) or {}
    if "title" not in fm:
        return None
    return WikiArticle(
        article_id=path.stem,
        title=str(fm["title"]),
        article_type=str(fm.get("type", "topic")),
        summary=str(fm.get("summary", "")),
        content=body.strip(),
        tags=_coerce_list(fm.get("tags")),
        backlinks=_coerce_list(fm.get("backlinks")),
        source_files=_coerce_list(fm.get("source_files")),
        created_at=_parse_date(fm.get("created")) or datetime.now().astimezone(),
        updated_at=_parse_date(fm.get("updated")) or datetime.now().astimezone(),
        path=path,
    )


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone()
    try:
        return datetime.fromisoformat(str(value)).astimezone()
    except (ValueError, TypeError):
        pass
    try:
        from datetime import date as date_type

        d = date_type.fromisoformat(str(value))
        return datetime(d.year, d.month, d.day).astimezone()
    except (ValueError, TypeError):
        return None
