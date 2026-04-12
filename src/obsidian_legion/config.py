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

    @classmethod
    def discover(cls, vault_root: Path | None = None) -> "LegionPaths":
        root = cls._resolve_vault_root(vault_root)
        action_points_root = root / "06-daily" / "action-points"
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


def _looks_like_vault(path: Path) -> bool:
    return (path / ".obsidian").exists() and (path / "06-daily" / "action-points").exists()
