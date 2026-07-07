from __future__ import annotations

import time
import uuid

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from obsidian_legion.vaultgraph.embedder import (
    COLLECTION,
    VECTOR_SIZE,
    VaultEmbedder,
    point_id,
)

DIM = VECTOR_SIZE  # 384


def unit(*pairs) -> list[float]:
    v = [0.0] * DIM
    for idx, val in pairs:
        v[idx] = val
    return v


def make_embedder(vectors_map: dict[str, list[float]]):
    client = QdrantClient(":memory:")

    def embed(texts):
        return [list(vectors_map[t]) for t in texts]

    emb = VaultEmbedder(client=client, embed_fn=embed, collection=COLLECTION)
    emb.ensure_collection()
    return emb, client


def _note(relpath, text, **extra):
    base = {"relpath": relpath, "title": relpath, "text": text, "folder": "",
            "tags": [], "mtime": 1.0, "sha256": "s"}
    base.update(extra)
    return base


def test_point_id_deterministic() -> None:
    assert point_id("a/b.md") == point_id("a/b.md")
    assert point_id("a/b.md") == str(
        uuid.uuid5(uuid.NAMESPACE_URL, "vaultgraph:a/b.md"))
    assert point_id("a/b.md") != point_id("a/c.md")


def test_ensure_collection_creates_384_cosine() -> None:
    client = QdrantClient(":memory:")
    emb = VaultEmbedder(client=client, embed_fn=lambda t: [[0.0] * DIM for _ in t])
    emb.ensure_collection()
    emb.ensure_collection()  # idempotent
    assert COLLECTION in {c.name for c in client.get_collections().collections}


def test_ensure_collection_dim_mismatch_raises() -> None:
    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=128, distance=Distance.COSINE))
    emb = VaultEmbedder(client=client, embed_fn=lambda t: [[0.0] * DIM for _ in t])
    with pytest.raises(ValueError):
        emb.ensure_collection()


def test_upsert_notes_payload_and_idempotent() -> None:
    emb, client = make_embedder({"AXIS:0": unit((0, 1.0))})
    note = _note("folder/note.md", "AXIS:0", title="My Note", folder="folder",
                 tags=["x", "y"], mtime=42.0, sha256="deadbeef")
    assert emb.upsert_notes([note]) == 1
    got = client.retrieve(collection_name=COLLECTION,
                          ids=[point_id("folder/note.md")], with_payload=True)
    assert len(got) == 1
    payload = got[0].payload
    assert payload["path"] == "folder/note.md"
    assert payload["title"] == "My Note"
    assert payload["folder"] == "folder"
    assert payload["tags"] == ["x", "y"]
    assert payload["sha256"] == "deadbeef"
    emb.upsert_notes([note])  # same relpath → same deterministic id
    assert client.count(collection_name=COLLECTION).count == 1


def test_knn_edges_thresholds() -> None:
    vmap = {
        "AXIS:0": unit((0, 1.0)),
        "DUP": unit((0, 1.0)),                       # cosine 1.0 vs AXIS:0
        "REL": unit((0, 0.7), (1, 0.714143)),        # |.|=1 → cosine 0.7 vs AXIS:0
        "ORTH": unit((2, 1.0)),                       # cosine 0 vs all
    }
    emb, _ = make_embedder(vmap)
    emb.upsert_notes([
        _note("a.md", "AXIS:0"), _note("dup.md", "DUP"),
        _note("rel.md", "REL"), _note("orth.md", "ORTH")])
    edges = emb.knn_edges(k=8, related_min=0.60, near_dup_min=0.92)
    a_edges = {e["dst"]: e for e in edges if e["src"] == "a.md"}
    assert a_edges["dup.md"]["annotation"] == "near_duplicate_of"
    assert a_edges["rel.md"]["annotation"] == "related_to"
    assert "orth.md" not in a_edges  # below related_min → no edge
    assert abs(a_edges["rel.md"]["weight"] - 0.7) < 1e-3


def test_search_masks_absent_by_default() -> None:
    vmap = {"AXIS:0": unit((0, 1.0)), "NEAR": unit((0, 0.95), (1, 0.312)),
            "anything": unit((0, 1.0))}
    emb, _ = make_embedder(vmap)
    emb.upsert_notes([_note("a.md", "AXIS:0"), _note("near.md", "NEAR")])
    paths = {r["path"] for r in emb.search("anything", k=5)}
    assert {"a.md", "near.md"} <= paths
    emb.mark_absent(["a.md"], time.time())
    assert "a.md" not in {r["path"] for r in emb.search("anything", k=5)}
    assert "a.md" in {r["path"] for r in emb.search("anything", k=5,
                                                    include_absent=True)}


def test_delete_points_purges() -> None:
    emb, client = make_embedder({"AXIS:0": unit((0, 1.0))})
    emb.upsert_notes([_note("a.md", "AXIS:0")])
    assert client.count(collection_name=COLLECTION).count == 1
    emb.delete_points(["a.md"])
    assert client.count(collection_name=COLLECTION).count == 0
