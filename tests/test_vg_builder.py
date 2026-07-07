import fcntl
import json
from pathlib import Path

from obsidian_legion.vaultgraph.builder import GraphBuilder
from obsidian_legion.vaultgraph.graphdb import GraphDB


class FakeEmbedder:
    def __init__(self):
        self.upserted, self.absent, self.deleted, self.knn = [], [], [], []
        self.raise_on_ensure = False

    def ensure_collection(self):
        if self.raise_on_ensure:
            raise RuntimeError("qdrant down")

    def upsert_notes(self, notes):
        self.upserted.extend(notes)
        return len(notes)

    def mark_absent(self, relpaths, ts):
        self.absent.extend(relpaths)

    def delete_points(self, relpaths):
        self.deleted.extend(relpaths)

    def knn_edges(self, k=8, related_min=0.60, near_dup_min=0.92):
        return list(self.knn)

    def search(self, query, k=8, include_absent=False):
        return []


def make_vault(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    return vault


def write(vault, rel, text):
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_full_build_writes_graph_manifest_and_embeds(tmp_path):
    vault = make_vault(tmp_path)
    write(vault, "apple.md", "# Apple\n\nlinks to [[banana]] and #fruit\n")
    write(vault, "banana.md", "# Banana\n\nback to [[apple]] #fruit\n")
    emb = FakeEmbedder()
    report = GraphBuilder(vault, embedder=emb).update(full=True)
    assert report["notes_seen"] == 2
    assert report["changed"] == 2
    assert report["embedded"] == 2
    assert report["qdrant_ok"] is True
    assert report["purged"] == 0 and report["absent_marked"] == 0
    assert "skipped" not in report
    assert {n["relpath"] for n in emb.upserted} == {"apple.md", "banana.md"}
    manifest = json.loads((vault / ".legion" / "graph-manifest.json").read_text())
    assert set(manifest) == {"apple.md", "banana.md"}
    assert (vault / ".legion" / "graph.sqlite").exists()


def test_incremental_reembeds_only_changed(tmp_path):
    vault = make_vault(tmp_path)
    write(vault, "apple.md", "# Apple\n[[banana]]\n")
    write(vault, "banana.md", "# Banana\n")
    GraphBuilder(vault, embedder=FakeEmbedder()).update(full=True)
    write(vault, "apple.md", "# Apple pie\n\nnew body [[banana]]\n")
    emb2 = FakeEmbedder()
    report = GraphBuilder(vault, embedder=emb2).update()
    assert report["changed"] == 1
    assert report["embedded"] == 1
    assert {n["relpath"] for n in emb2.upserted} == {"apple.md"}


def test_absent_note_masked_not_deleted(tmp_path):
    vault = make_vault(tmp_path)
    write(vault, "alpha.md", "# Alpha\n")
    write(vault, "keepme.md", "# Keepme\n")
    GraphBuilder(vault, embedder=FakeEmbedder()).update(full=True)
    (vault / "keepme.md").unlink()
    emb2 = FakeEmbedder()
    report = GraphBuilder(vault, embedder=emb2).update()
    assert report["absent_marked"] == 1
    assert report["purged"] == 0
    assert emb2.absent == ["keepme.md"]
    db = GraphDB(vault / ".legion" / "graph.sqlite")
    assert db.search_lexical("keepme", include_absent=True)       # tombstone still findable
    assert not db.search_lexical("keepme", include_absent=False)  # masked by default


def test_hard_private_transition_purges_both_stores(tmp_path):
    vault = make_vault(tmp_path)
    write(vault, "m/agenda.md", "# Agenda\n")
    write(vault, "other.md", "# Other\n")
    GraphBuilder(vault, embedder=FakeEmbedder()).update(full=True)
    (vault / "m" / "agenda.md").unlink()
    write(vault, "m/.murphy_private/agenda.md", "# Secret now\n")
    emb2 = FakeEmbedder()
    report = GraphBuilder(vault, embedder=emb2).update()
    assert report["purged"] == 1
    assert report["absent_marked"] == 0
    assert emb2.deleted == ["m/agenda.md"]
    manifest = json.loads((vault / ".legion" / "graph-manifest.json").read_text())
    assert "m/agenda.md" not in manifest
    db = GraphDB(vault / ".legion" / "graph.sqlite")
    assert not db.search_lexical("agenda", include_absent=True)   # gone entirely


def test_nested_murphy_private_excluded(tmp_path):
    vault = make_vault(tmp_path)
    write(vault, "pub.md", "# Public\n")
    write(vault, "x/y/.murphy_private/secret.md", "# Secret\n")
    emb = FakeEmbedder()
    report = GraphBuilder(vault, embedder=emb).update(full=True)
    assert report["notes_seen"] == 1
    assert {n["relpath"] for n in emb.upserted} == {"pub.md"}
    db = GraphDB(vault / ".legion" / "graph.sqlite")
    assert not db.search_lexical("Secret", include_absent=True)


def test_second_concurrent_run_skips(tmp_path):
    vault = make_vault(tmp_path)
    write(vault, "a.md", "# A\n")
    (vault / ".legion").mkdir(parents=True)
    lock = open(vault / ".legion" / ".lock", "w")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        report = GraphBuilder(vault, embedder=FakeEmbedder()).update()
        assert report == {"skipped": "already_running"}
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def test_qdrant_failure_structural_still_builds(tmp_path):
    vault = make_vault(tmp_path)
    write(vault, "a.md", "# A\n[[b]]\n")
    write(vault, "b.md", "# B\n")
    emb = FakeEmbedder()
    emb.raise_on_ensure = True
    report = GraphBuilder(vault, embedder=emb).update(full=True)
    assert report["qdrant_ok"] is False
    assert report["notes_seen"] == 2
    assert report["semantic_edges"] == 0
    assert (vault / ".legion" / "graph.sqlite").exists()
    manifest = json.loads((vault / ".legion" / "graph-manifest.json").read_text())
    assert set(manifest) == {"a.md", "b.md"}


def test_skip_embeddings_builds_structure_only(tmp_path):
    vault = make_vault(tmp_path)
    write(vault, "a.md", "# A\n[[b]]\n")
    write(vault, "b.md", "# B\n")
    emb = FakeEmbedder()
    report = GraphBuilder(vault, embedder=emb).update(full=True, skip_embeddings=True)
    assert report["qdrant_ok"] is False
    assert report["embedded"] == 0
    assert emb.upserted == []
    assert (vault / ".legion" / "graph.sqlite").exists()
