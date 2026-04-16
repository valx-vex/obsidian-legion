#!/usr/bin/env python3
"""sync_vault_to_qdrant.py -- Sync an Obsidian vault to Qdrant for semantic search.

Layer 3 of the VALX memory architecture: walks a vault for .md files,
generates embeddings via Ollama (nomic-embed-text), and upserts them into
a Qdrant collection with metadata.

Tracks file hashes in vault_root/wiki/.qdrant_sync.json so unchanged
files are skipped on subsequent runs.

Usage:
    python scripts/sync_vault_to_qdrant.py --vault-root /path/to/vault
    python scripts/sync_vault_to_qdrant.py --vault-root /path/to/vault --limit 10
    python scripts/sync_vault_to_qdrant.py --vault-root /path/to/vault --collection my_collection
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXCLUDE_DIRS: set[str] = {
    "wiki",
    ".obsidian",
    ".git",
    "node_modules",
    ".venv",
    "__pycache__",
    ".smart-env",
}

DEFAULT_COLLECTION = "vexpedia"
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
VECTOR_SIZE = 768
SYNC_STATE_FILENAME = ".qdrant_sync.json"
CONTENT_PREVIEW_LENGTH = 500

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_of(content: str) -> str:
    """Return hex SHA-256 digest of *content*."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def deterministic_uuid(path: str) -> str:
    """Create a reproducible UUID-5 from a relative file path.

    This ensures the same file always maps to the same Qdrant point id,
    making upserts idempotent.
    """
    ns = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    return str(uuid.uuid5(ns, path))


def extract_title(content: str, fallback: str) -> str:
    """Return the first markdown heading, or *fallback* if none found."""
    match = re.search(r"^#\s+(.+)", content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return fallback


def file_modified_iso(path: Path) -> str:
    """Return the file's mtime as an ISO-8601 UTC string."""
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Sync-state persistence
# ---------------------------------------------------------------------------


def load_sync_state(sync_path: Path) -> dict[str, str]:
    """Load the path->hash mapping from disk."""
    if sync_path.exists():
        try:
            return json.loads(sync_path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_sync_state(sync_path: Path, state: dict[str, str]) -> None:
    """Persist the path->hash mapping to disk."""
    sync_path.parent.mkdir(parents=True, exist_ok=True)
    sync_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", "utf-8")


# ---------------------------------------------------------------------------
# Vault walking
# ---------------------------------------------------------------------------


def walk_vault(vault_root: Path) -> list[Path]:
    """Yield all .md files under *vault_root*, respecting EXCLUDE_DIRS."""
    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(vault_root):
        # Prune excluded directories in-place so os.walk skips them.
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.lower().endswith(".md"):
                results.append(Path(dirpath) / fn)
    results.sort()
    return results


# ---------------------------------------------------------------------------
# Ollama embedding
# ---------------------------------------------------------------------------


def get_embedding(
    client: httpx.Client,
    text: str,
    *,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    model: str = DEFAULT_EMBED_MODEL,
) -> list[float]:
    """Call Ollama's /api/embed endpoint and return the embedding vector."""
    resp = client.post(
        f"{ollama_url}/api/embed",
        json={"model": model, "input": text},
        timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json()
    # The response contains {"embeddings": [[...]]}.
    embeddings = data.get("embeddings") or data.get("embedding")
    if isinstance(embeddings, list) and len(embeddings) > 0:
        vec = embeddings[0] if isinstance(embeddings[0], list) else embeddings
        return vec
    raise ValueError(f"Unexpected Ollama embed response: {data!r}")


# ---------------------------------------------------------------------------
# Qdrant operations -- tries qdrant_client, falls back to raw HTTP
# ---------------------------------------------------------------------------

_USE_QDRANT_CLIENT: bool | None = None


def _have_qdrant_client() -> bool:
    global _USE_QDRANT_CLIENT
    if _USE_QDRANT_CLIENT is None:
        try:
            import qdrant_client  # noqa: F401

            _USE_QDRANT_CLIENT = True
        except ImportError:
            _USE_QDRANT_CLIENT = False
    return _USE_QDRANT_CLIENT


class QdrantBackend:
    """Thin abstraction over Qdrant -- uses the Python client if installed,
    otherwise falls back to the raw HTTP REST API via httpx."""

    def __init__(self, url: str, collection: str, vector_size: int = VECTOR_SIZE):
        self.url = url.rstrip("/")
        self.collection = collection
        self.vector_size = vector_size

        if _have_qdrant_client():
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=self.url)
            self._http: httpx.Client | None = None
        else:
            self._client = None  # type: ignore[assignment]
            self._http = httpx.Client(timeout=30.0)

    # -- ensure collection exists ----------------------------------------

    def ensure_collection(self) -> None:
        if self._client is not None:
            self._ensure_collection_sdk()
        else:
            self._ensure_collection_http()

    def _ensure_collection_sdk(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        collections = [c.name for c in self._client.get_collections().collections]
        if self.collection not in collections:
            self._client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(
                    size=self.vector_size, distance=Distance.COSINE
                ),
            )
            print(f"  Created Qdrant collection '{self.collection}'")
        else:
            print(f"  Qdrant collection '{self.collection}' already exists")

    def _ensure_collection_http(self) -> None:
        assert self._http is not None
        resp = self._http.get(f"{self.url}/collections/{self.collection}")
        if resp.status_code == 404 or (
            resp.status_code == 200
            and resp.json().get("status") == "error"
        ):
            create_resp = self._http.put(
                f"{self.url}/collections/{self.collection}",
                json={
                    "vectors": {
                        "size": self.vector_size,
                        "distance": "Cosine",
                    }
                },
            )
            create_resp.raise_for_status()
            print(f"  Created Qdrant collection '{self.collection}'")
        else:
            resp.raise_for_status()
            print(f"  Qdrant collection '{self.collection}' already exists")

    # -- upsert a single point ------------------------------------------

    def upsert(
        self,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        if self._client is not None:
            self._upsert_sdk(point_id, vector, payload)
        else:
            self._upsert_http(point_id, vector, payload)

    def _upsert_sdk(
        self, point_id: str, vector: list[float], payload: dict[str, Any]
    ) -> None:
        from qdrant_client.models import PointStruct

        self._client.upsert(
            collection_name=self.collection,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    def _upsert_http(
        self, point_id: str, vector: list[float], payload: dict[str, Any]
    ) -> None:
        assert self._http is not None
        body = {
            "points": [
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": payload,
                }
            ]
        }
        resp = self._http.put(
            f"{self.url}/collections/{self.collection}/points",
            json=body,
        )
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Main sync logic
# ---------------------------------------------------------------------------


def sync(
    vault_root: Path,
    *,
    qdrant_url: str = DEFAULT_QDRANT_URL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    collection: str = DEFAULT_COLLECTION,
    limit: int | None = None,
) -> None:
    vault_root = vault_root.resolve()
    if not vault_root.is_dir():
        print(f"Error: vault root does not exist: {vault_root}", file=sys.stderr)
        sys.exit(1)

    sync_path = vault_root / "wiki" / SYNC_STATE_FILENAME
    sync_state = load_sync_state(sync_path)

    print(f"Vault root : {vault_root}")
    print(f"Qdrant     : {qdrant_url}  collection={collection}")
    print(f"Ollama     : {ollama_url}  model={DEFAULT_EMBED_MODEL}")
    print(f"Sync state : {sync_path}  ({len(sync_state)} cached entries)")
    print()

    # Discover files.
    all_files = walk_vault(vault_root)
    total = len(all_files)
    if limit is not None:
        all_files = all_files[:limit]
    process_count = len(all_files)
    print(f"Found {total} .md files, processing {process_count}")

    # Connect to Qdrant.
    backend = QdrantBackend(qdrant_url, collection)
    backend.ensure_collection()

    # Prepare HTTP client for Ollama.
    http = httpx.Client(timeout=120.0)

    new_count = 0
    updated_count = 0
    skipped_count = 0

    for idx, filepath in enumerate(all_files, start=1):
        rel = str(filepath.relative_to(vault_root))
        try:
            content = filepath.read_text("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"  [{idx}/{process_count}] SKIP {rel}  ({exc})")
            skipped_count += 1
            continue

        content_hash = sha256_of(content)

        # Skip unchanged files.
        if sync_state.get(rel) == content_hash:
            skipped_count += 1
            continue

        is_new = rel not in sync_state

        # Generate embedding.
        try:
            vector = get_embedding(http, content, ollama_url=ollama_url)
        except Exception as exc:
            print(f"  [{idx}/{process_count}] EMBED FAIL {rel}  ({exc})")
            continue

        # Build payload.
        title = extract_title(content, filepath.stem)
        modified = file_modified_iso(filepath)
        preview = content[:CONTENT_PREVIEW_LENGTH]
        payload = {
            "path": rel,
            "title": title,
            "modified": modified,
            "content_preview": preview,
        }

        # Upsert to Qdrant.
        point_id = deterministic_uuid(rel)
        try:
            backend.upsert(point_id, vector, payload)
        except Exception as exc:
            print(f"  [{idx}/{process_count}] UPSERT FAIL {rel}  ({exc})")
            continue

        # Update sync state.
        sync_state[rel] = content_hash
        if is_new:
            new_count += 1
        else:
            updated_count += 1

        label = "NEW" if is_new else "UPD"
        print(f"  [{idx}/{process_count}] {label} {rel}")

    # Persist sync state.
    save_sync_state(sync_path, sync_state)

    print()
    synced = new_count + updated_count
    print(
        f"Synced {synced}/{process_count} files, "
        f"{new_count} new, {updated_count} updated, "
        f"{skipped_count} skipped (unchanged)"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync Obsidian vault .md files to Qdrant for semantic search.",
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        required=True,
        help="Root directory of the Obsidian vault.",
    )
    parser.add_argument(
        "--qdrant-url",
        default=DEFAULT_QDRANT_URL,
        help=f"Qdrant server URL (default: {DEFAULT_QDRANT_URL}).",
    )
    parser.add_argument(
        "--ollama-url",
        default=DEFAULT_OLLAMA_URL,
        help=f"Ollama server URL (default: {DEFAULT_OLLAMA_URL}).",
    )
    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION,
        help=f"Qdrant collection name (default: {DEFAULT_COLLECTION}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N files (for testing).",
    )
    args = parser.parse_args()

    sync(
        vault_root=args.vault_root,
        qdrant_url=args.qdrant_url,
        ollama_url=args.ollama_url,
        collection=args.collection,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
