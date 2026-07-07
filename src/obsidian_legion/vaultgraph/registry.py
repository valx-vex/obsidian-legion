from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_REGISTRY = Path.home() / ".legion" / "vaults.json"


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Path]:
    """Read the vault-roots registry. Missing/corrupt file → empty mapping."""
    registry_path = Path(path)
    if not registry_path.exists():
        return {}
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(name): Path(root) for name, root in data.items()}


def default_vault(path: Path = DEFAULT_REGISTRY) -> tuple[str, Path]:
    """First registered (name, root). Raises FileNotFoundError if none."""
    registry = load_registry(path)
    if not registry:
        raise FileNotFoundError(
            "No vaults registered. Add one to ~/.legion/vaults.json "
            "or pass --vault <path>."
        )
    name = next(iter(registry))
    return name, registry[name]


def register_vault(name: str, root: Path, path: Path = DEFAULT_REGISTRY) -> None:
    """Insert/overwrite a name→root entry (root stored absolute). Atomic write."""
    registry_path = Path(path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, str] = {}
    if registry_path.exists():
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    data[str(name)] = str(Path(root).expanduser().resolve())
    tmp = registry_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, registry_path)
