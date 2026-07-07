"""Qdrant embedder for the R5 semantic vault (heavy deps lazily imported).

Collection ``vault_eternal``, all-MiniLM-L6-v2, 384-dim, Cosine — the house
contract. Deterministic point ids (uuid5 of the vault-relative path). Camp B:
absent notes get an ``absent_since`` payload flag (masked, never deleted) —
except ``delete_points`` (the ``.murphy_private`` hard-exclusion purge).
Semantic ``knn_edges`` are post-hoc annotations (cosine ≥ 0.60 → related_to;
≥ 0.92 → near_duplicate_of); they never create or gate nodes. Every heavy
import (qdrant_client, numpy, sentence_transformers) is inside a method, so the
live MCP server imports this module without the [vaultgraph] extra.
"""
from __future__ import annotations

import uuid

COLLECTION = "vault_eternal"
VECTOR_SIZE = 384
MODEL_NAME = "all-MiniLM-L6-v2"


def point_id(relpath: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "vaultgraph:" + relpath))


def _existing_dim(info) -> int | None:
    try:
        vectors = info.config.params.vectors
    except AttributeError:
        return None
    if vectors is None:
        return None
    size = getattr(vectors, "size", None)
    if size is not None:
        return size
    if isinstance(vectors, dict):
        for value in vectors.values():
            candidate = getattr(value, "size", None)
            if candidate is not None:
                return candidate
    return None


class VaultEmbedder:
    def __init__(self, qdrant_url: str = "http://localhost:6333",
                 collection: str = COLLECTION, client=None, embed_fn=None) -> None:
        self.qdrant_url = qdrant_url
        self.collection = collection
        self._client = client
        self._embed_fn = embed_fn
        self._model = None

    def _get_client(self):
        if self._client is None:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(url=self.qdrant_url)
        return self._client

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embed_fn is not None:
            return self._embed_fn(texts)
        from sentence_transformers import SentenceTransformer
        if self._model is None:
            self._model = SentenceTransformer(MODEL_NAME)  # truncates at 256 tokens
        return [vector.tolist() for vector in self._model.encode(list(texts))]

    def ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams
        client = self._get_client()
        existing = {c.name for c in client.get_collections().collections}
        if self.collection in existing:
            dim = _existing_dim(client.get_collection(self.collection))
            if dim is not None and dim != VECTOR_SIZE:
                raise ValueError(
                    f"Collection {self.collection!r} exists with dim {dim}, "
                    f"expected {VECTOR_SIZE}; refusing to upsert (house contract).")
            return
        client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE))

    def upsert_notes(self, notes: list[dict]) -> int:
        from qdrant_client.models import PointStruct
        notes = [n for n in (notes or []) if n.get("relpath")]
        if not notes:
            return 0
        vectors = self._embed([n.get("text", "") for n in notes])
        client = self._get_client()
        points = []
        for note, vector in zip(notes, vectors):
            relpath = note["relpath"]
            payload = {
                "path": relpath,
                "title": note.get("title", ""),
                "tags": list(note.get("tags") or []),
                "folder": note.get("folder", ""),
                "mtime": note.get("mtime"),
                "sha256": note.get("sha256"),
            }
            points.append(PointStruct(id=point_id(relpath),
                                      vector=list(vector), payload=payload))
        client.upsert(collection_name=self.collection, points=points)
        return len(points)

    def mark_absent(self, relpaths: list[str], ts: float) -> None:
        if not relpaths:
            return
        client = self._get_client()
        client.set_payload(
            collection_name=self.collection,
            payload={"absent_since": float(ts)},
            points=[point_id(rp) for rp in relpaths])

    def delete_points(self, relpaths: list[str]) -> None:
        if not relpaths:
            return
        from qdrant_client.models import PointIdsList
        client = self._get_client()
        client.delete(
            collection_name=self.collection,
            points_selector=PointIdsList(points=[point_id(rp) for rp in relpaths]))

    def knn_edges(self, k: int = 8, related_min: float = 0.60,
                  near_dup_min: float = 0.92) -> list[dict]:
        import numpy as np
        client = self._get_client()
        rows = []
        offset = None
        while True:
            batch, offset = client.scroll(
                collection_name=self.collection, limit=1000,
                with_payload=True, with_vectors=True, offset=offset)
            rows.extend(batch)
            if offset is None:
                break
        rows = [r for r in rows if not (r.payload or {}).get("absent_since")]
        if len(rows) < 2:
            return []
        paths = [(r.payload or {}).get("path") for r in rows]
        vectors = np.array([r.vector for r in rows], dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        unit_vectors = vectors / norms
        sims = unit_vectors @ unit_vectors.T
        edges: list[dict] = []
        for i in range(len(rows)):
            taken = 0
            for j in np.argsort(-sims[i]):
                if j == i:
                    continue
                score = float(sims[i][j])
                if score < related_min:
                    break
                annotation = ("near_duplicate_of" if score >= near_dup_min
                              else "related_to")
                edges.append({"src": paths[i], "dst": paths[int(j)],
                              "weight": score, "annotation": annotation})
                taken += 1
                if taken >= k:
                    break
        return edges

    def search(self, query: str, k: int = 8,
               include_absent: bool = False) -> list[dict]:
        client = self._get_client()
        vector = self._embed([query])[0]
        fetch = k if include_absent else min(max(k * 4, k + 10), 256)
        points = client.query_points(
            collection_name=self.collection, query=list(vector),
            limit=fetch, with_payload=True).points
        out: list[dict] = []
        for point in points:
            payload = point.payload or {}
            if not include_absent and payload.get("absent_since") is not None:
                continue
            out.append({"path": payload.get("path"), "title": payload.get("title"),
                        "score": point.score, "tags": payload.get("tags", []),
                        "folder": payload.get("folder", "")})
            if len(out) >= k:
                break
        return out
