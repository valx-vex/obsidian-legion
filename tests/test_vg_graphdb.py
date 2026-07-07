from __future__ import annotations

from pathlib import Path

from obsidian_legion.vaultgraph import graphdb
from obsidian_legion.vaultgraph.graphdb import GraphDB, SCHEMA_VERSION


def _db(tmp_path: Path) -> GraphDB:
    return GraphDB(tmp_path / ".legion" / "graph.sqlite")


def _node(id, kind, title, key, path):
    return {"id": id, "kind": kind, "title": title, "canonical_key": key,
            "path": path, "mtime": 1.0, "sha256": "x", "community_id": None,
            "centrality": None, "pagerank": None, "absent_since": None}


def _seed(db: GraphDB) -> None:
    nodes = [
        _node("notes/alpha.md", "note", "Alpha", "alpha", "notes/alpha.md"),
        _node("notes/beta.md", "note", "Beta", "beta", "notes/beta.md"),
        _node("notes/gamma.md", "note", "Gamma flame", "gamma flame", "notes/gamma.md"),
        _node("phantom:valentin", "phantom", "Valentin", "valentin", None),
    ]
    edges = [
        {"src": "notes/alpha.md", "dst": "notes/beta.md", "kind": "wikilink",
         "weight": 1.0, "annotation": None},
        {"src": "notes/beta.md", "dst": "notes/gamma.md", "kind": "wikilink",
         "weight": 1.0, "annotation": None},
        {"src": "notes/alpha.md", "dst": "phantom:valentin", "kind": "wikilink",
         "weight": 1.0, "annotation": None},
        {"src": "notes/alpha.md", "dst": "notes/gamma.md", "kind": "semantic",
         "weight": 0.7, "annotation": "related_to"},
    ]
    fts_rows = [
        {"id": "notes/alpha.md", "title": "Alpha", "body": "the sacred flame burns"},
        {"id": "notes/beta.md", "title": "Beta", "body": "beta discusses bridges"},
        {"id": "notes/gamma.md", "title": "Gamma flame",
         "body": "gamma sacred flame glory"},
    ]
    db.rebuild(nodes, edges, fts_rows)


def test_fts_available_is_bool() -> None:
    assert isinstance(graphdb.fts_available(), bool)
    assert SCHEMA_VERSION == 1


def test_rebuild_atomic_no_temp_left(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _seed(db)
    assert db.db_path.exists()
    assert list(db.db_path.parent.glob(".graph-*")) == []
    st = db.stats()
    assert st["nodes"] == 4 and st["edges"] == 4
    assert st["kinds"]["note"] == 3 and st["kinds"]["phantom"] == 1
    assert st["schema_version"] == 1


def test_rebuild_replaces_not_merges(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _seed(db)
    db.rebuild([_node("solo.md", "note", "Solo", "solo", "solo.md")], [],
               [{"id": "solo.md", "title": "Solo", "body": "lonely"}])
    st = db.stats()
    assert st["nodes"] == 1 and st["edges"] == 0
    assert db.neighbors("notes/alpha.md")["center"] is None  # old graph gone


def test_mark_absent_masks(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _seed(db)
    db.mark_absent(["notes/beta.md"], 999.0)
    assert db.stats()["absent"] == 1
    ids = {n["id"] for n in db.neighbors("notes/alpha.md", depth=1)["nodes"]}
    assert "notes/beta.md" not in ids
    ids2 = {n["id"] for n in db.neighbors("notes/alpha.md", depth=1,
                                          include_absent=True)["nodes"]}
    assert "notes/beta.md" in ids2


def test_purge_removes_everything(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _seed(db)
    db.purge(["notes/gamma.md"])
    st = db.stats()
    assert st["nodes"] == 3
    assert st["edges"] == 2  # beta-gamma and alpha-gamma dropped
    assert db.search_lexical("glory", k=8) == []  # fts row gone
    assert db.neighbors("notes/gamma.md")["center"] is None


def test_set_analytics_and_communities(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _seed(db)
    node_updates = {
        "notes/alpha.md": {"community_id": 0, "centrality": 0.5, "pagerank": 0.4},
        "notes/beta.md": {"community_id": 0, "centrality": 0.2, "pagerank": 0.3},
        "notes/gamma.md": {"community_id": 1, "centrality": 0.1, "pagerank": 0.2},
    }
    comms = [
        {"community_id": 0, "name": "flame cluster", "size": 2,
         "top_members": ["Alpha", "Beta"]},
        {"community_id": 1, "name": "gamma cluster", "size": 1,
         "top_members": ["Gamma flame"]},
    ]
    db.set_analytics(node_updates, communities=comms)
    got = db.communities()
    assert {c["community_id"] for c in got} == {0, 1}
    top = next(c for c in got if c["community_id"] == 0)
    assert top["name"] == "flame cluster"
    assert top["size"] == 2
    assert top["top_members"] == ["Alpha", "Beta"]
    assert db.stats()["communities"] == 2
    center = db.neighbors("notes/alpha.md", depth=1)["center"]
    assert center["pagerank"] == 0.4 and center["community_id"] == 0


def test_search_lexical_and_absent_mask(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _seed(db)
    res = db.search_lexical("flame", k=8)
    ids = [r["id"] for r in res]
    assert "notes/gamma.md" in ids and "notes/alpha.md" in ids
    assert ids[0] == "notes/gamma.md"  # title + body both match → ranks first
    db.mark_absent(["notes/gamma.md"], 1.0)
    assert "notes/gamma.md" not in [r["id"] for r in db.search_lexical("flame", k=8)]
    assert "notes/gamma.md" in [
        r["id"] for r in db.search_lexical("flame", k=8, include_absent=True)]


def test_search_lexical_like_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(graphdb, "fts_available", lambda: False)
    db = _db(tmp_path)
    _seed(db)  # rebuild now builds a plain (LIKE-scored) table
    assert db.stats()["fts_enabled"] is False
    ids = [r["id"] for r in db.search_lexical("flame", k=8)]
    assert "notes/gamma.md" in ids and "notes/alpha.md" in ids
    assert ids[0] == "notes/gamma.md"  # title(+10)+body(+1) outranks body-only(+1)


def test_neighbors_typed_and_depth(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _seed(db)
    all1 = db.neighbors("notes/alpha.md", depth=1)
    assert all1["center"]["id"] == "notes/alpha.md"
    assert {"notes/beta.md", "notes/gamma.md", "phantom:valentin"} <= {
        n["id"] for n in all1["nodes"]}
    wiki1 = db.neighbors("notes/alpha.md", depth=1, kinds=["wikilink"])
    ids = {n["id"] for n in wiki1["nodes"]}
    assert "notes/gamma.md" not in ids  # alpha-gamma is a semantic edge, filtered
    assert {"notes/beta.md", "phantom:valentin"} <= ids
    wiki2 = db.neighbors("notes/alpha.md", depth=2, kinds=["wikilink"])
    assert "notes/gamma.md" in {n["id"] for n in wiki2["nodes"]}  # via beta


def test_neighbors_by_canonical_key(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _seed(db)
    res = db.neighbors("valentin", depth=1)  # resolves phantom by canonical_key
    assert res["center"]["id"] == "phantom:valentin"
    assert "notes/alpha.md" in {n["id"] for n in res["nodes"]}


def test_shortest_path(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _seed(db)
    direct = [n["id"] for n in db.shortest_path("notes/alpha.md", "notes/gamma.md")]
    assert direct == ["notes/alpha.md", "notes/gamma.md"]  # direct semantic edge
    via = [n["id"] for n in db.shortest_path("valentin", "notes/gamma.md")]
    assert via[0] == "phantom:valentin" and via[-1] == "notes/gamma.md"
    assert len(via) == 3
    assert db.shortest_path("notes/alpha.md", "does/not/exist.md") == []
    same = [n["id"] for n in db.shortest_path("notes/alpha.md", "notes/alpha.md")]
    assert same == ["notes/alpha.md"]
