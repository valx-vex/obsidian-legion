from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LegionPaths:
    vault_root: Path
    action_points_root: Path
    tasks_root: Path
    dashboards_root: Path
    reviews_root: Path
    templates_root: Path
    config_root: Path
    state_root: Path
    daily_root: Path
    agents_file: Path
    counter_file: Path
    # Wiki paths (Karpathy LLM Wiki pattern)
    wiki_root: Path
    raw_root: Path
    wiki_index: Path
    wiki_log: Path
    wiki_state: Path
    wiki_manifest: Path
    wiki_entities: Path
    wiki_topics: Path
    wiki_sources: Path
    wiki_config: Path
    # Qdrant vector search settings
    qdrant_url: str
    qdrant_collection: str

    @classmethod
    def discover(cls, vault_root: Path | None = None) -> "LegionPaths":
        root = cls._resolve_vault_root(vault_root)
        action_points_root = root / "06-daily" / "action-points"
        wiki_root = root / "wiki"
        return cls(
            vault_root=root,
            action_points_root=action_points_root,
            tasks_root=action_points_root / "tasks",
            dashboards_root=action_points_root / "dashboards",
            reviews_root=action_points_root / "reviews",
            templates_root=action_points_root / "templates",
            config_root=action_points_root / "config",
            state_root=action_points_root / "state",
            daily_root=action_points_root / "daily",
            agents_file=action_points_root / "config" / "agents.yaml",
            counter_file=action_points_root / "state" / "id-counter.json",
            wiki_root=wiki_root,
            raw_root=root / "raw",
            wiki_index=wiki_root / "index.md",
            wiki_log=wiki_root / "log.md",
            wiki_state=wiki_root / "state.md",
            wiki_manifest=wiki_root / ".manifest.json",
            wiki_entities=wiki_root / "entities",
            wiki_topics=wiki_root / "topics",
            wiki_sources=wiki_root / "sources",
            wiki_config=wiki_root / ".wiki_config.yaml",
            qdrant_url=os.environ.get("QDRANT_URL", "http://localhost:6333"),
            qdrant_collection=os.environ.get("QDRANT_COLLECTION", "vexpedia"),
        )

    @staticmethod
    def _resolve_vault_root(explicit_root: Path | None) -> Path:
        if explicit_root is not None:
            root = explicit_root.expanduser().resolve()
            if _looks_like_vault(root):
                return root
            raise FileNotFoundError(f"{root} does not look like an Obsidian vault root.")

        env_root = os.environ.get("OBSIDIAN_LEGION_VAULT")
        if env_root:
            root = Path(env_root).expanduser().resolve()
            if _looks_like_vault(root):
                return root

        for start in [Path.cwd(), *Path.cwd().parents]:
            if _looks_like_vault(start):
                return start.resolve()

        raise FileNotFoundError(
            "Could not discover vault root. Pass --vault-root or set OBSIDIAN_LEGION_VAULT."
        )

    def ensure_layout(self) -> None:
        for path in [
            self.action_points_root,
            self.tasks_root,
            self.dashboards_root,
            self.reviews_root,
            self.templates_root,
            self.config_root,
            self.state_root,
            self.daily_root,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def ensure_wiki_layout(self) -> None:
        for path in [
            self.wiki_root,
            self.raw_root,
            self.wiki_entities,
            self.wiki_topics,
            self.wiki_sources,
        ]:
            path.mkdir(parents=True, exist_ok=True)


def _looks_like_vault(path: Path) -> bool:
    return (path / ".obsidian").exists() and (path / "06-daily" / "action-points").exists()
