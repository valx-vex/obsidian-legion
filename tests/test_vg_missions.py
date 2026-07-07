# tests/test_vg_missions.py
import sqlite3
from pathlib import Path

from obsidian_legion.vaultgraph.missions import (
    PageSpec, build_mission_prompt, select_pages,
)


class FakeGraphDB:
    """Minimal stand-in for GraphDB: owns a sqlite file with the locked
    nodes/edges/communities schema and exposes it via db_path (the same
    public attribute the real GraphDB carries from its constructor arg)."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, title TEXT,
                canonical_key TEXT, path TEXT, mtime REAL, sha256 TEXT,
                community_id INTEGER, centrality REAL, pagerank REAL,
                absent_since REAL);
            CREATE TABLE edges (src TEXT, dst TEXT, kind TEXT, weight REAL,
                annotation TEXT);
            CREATE TABLE communities (community_id INTEGER PRIMARY KEY, name TEXT,
                size INTEGER, top_members_json TEXT);
            """
        )
        conn.commit()
        conn.close()

    def add_note(self, node_id, path, pagerank, community_id=None, title=None):
        self._exec(
            "INSERT INTO nodes (id, kind, title, canonical_key, path, pagerank, "
            "community_id, absent_since) VALUES (?,?,?,?,?,?,?,NULL)",
            (node_id, "note", title or path, path.lower(), path, pagerank, community_id))

    def add_phantom(self, node_id, canonical_key, title=None):
        self._exec(
            "INSERT INTO nodes (id, kind, title, canonical_key, path, pagerank, "
            "community_id, absent_since) VALUES (?,?,?,?,NULL,0.0,NULL,NULL)",
            (node_id, "phantom", title or canonical_key, canonical_key))

    def add_wikilink(self, src, dst):
        self._exec("INSERT INTO edges (src, dst, kind, weight) VALUES (?,?,?,1.0)",
                   (src, dst, "wikilink"))

    def name_community(self, community_id, name):
        self._exec("INSERT INTO communities (community_id, name, size, "
                   "top_members_json) VALUES (?,?,0,'[]')", (community_id, name))

    def _exec(self, sql, params):
        conn = sqlite3.connect(self.db_path)
        conn.execute(sql, params)
        conn.commit()
        conn.close()


def _db(tmp_path):
    return FakeGraphDB(tmp_path / "graph.sqlite")


def test_topics_qualify_at_min_size_and_rank_by_size_times_pagerank(tmp_path):
    db = _db(tmp_path)
    # community 1: 5 notes, mean pagerank 0.2 -> score 1.0
    for i in range(5):
        db.add_note(f"c1n{i}", f"c1/{i}.md", 0.2, community_id=1)
    # community 2: 6 notes, mean pagerank 0.5 -> score 3.0 (ranks first)
    for i in range(6):
        db.add_note(f"c2n{i}", f"c2/{i}.md", 0.5, community_id=2)
    # community 3: 4 notes -> below min_community_size, dropped
    for i in range(4):
        db.add_note(f"c3n{i}", f"c3/{i}.md", 0.9, community_id=3)
    db.name_community(1, "First")
    db.name_community(2, "Second")
    specs = select_pages(db, min_community_size=5, pagerank_percentile=99.9)
    topics = [s for s in specs if s.kind == "topic"]
    assert [s.key for s in topics] == ["2", "1"]           # higher score first
    assert topics[0].title == "Second"
    assert topics[0].wiki_relpath.startswith("topics/")
    assert all(sr.startswith("c2/") for sr in topics[0].source_relpaths)


def test_entities_selected_above_p95_pagerank(tmp_path):
    db = _db(tmp_path)
    for i in range(20):
        db.add_note(f"n{i}", f"notes/{i}.md", pagerank=float(i))  # 0..19
    # p95 nearest-rank over 20 values -> index 18 -> threshold 18.0 => notes 18,19
    specs = select_pages(db, min_community_size=999, pagerank_percentile=95.0)
    entities = [s for s in specs if s.kind == "entity"]
    keys = {s.key for s in entities}
    assert keys == {"n18", "n19"}
    assert entities[0].key == "n19"                        # ranked by pagerank desc


def test_resolving_phantoms_qualify_by_degree(tmp_path):
    db = _db(tmp_path)
    for i in range(6):
        db.add_note(f"n{i}", f"notes/{i}.md", pagerank=0.01)
    db.add_phantom("phantom:valentin", "valentin", title="Valentin")
    for i in range(5):                                     # degree 5 >= threshold
        db.add_wikilink(f"n{i}", "phantom:valentin")
    db.add_phantom("phantom:rare", "rare")
    db.add_wikilink("n0", "phantom:rare")                 # degree 1 -> dropped
    specs = select_pages(db, min_community_size=999, pagerank_percentile=99.9,
                         phantom_min_degree=5)
    entity_keys = {s.key for s in specs if s.kind == "entity"}
    assert "phantom:valentin" in entity_keys
    assert "phantom:rare" not in entity_keys
    valentin = next(s for s in specs if s.key == "phantom:valentin")
    assert sorted(valentin.source_relpaths) == [f"notes/{i}.md" for i in range(5)]


def test_max_pages_caps_and_defers(tmp_path):
    db = _db(tmp_path)
    for c in range(1, 11):                                 # 10 qualifying communities
        for i in range(5):
            db.add_note(f"c{c}n{i}", f"c{c}/{i}.md", pagerank=float(c), community_id=c)
    specs = select_pages(db, max_pages=3, min_community_size=5,
                         pagerank_percentile=99.9)
    assert len(specs) == 3
    # deterministic: highest size*mean_pagerank first (community 10, 9, 8)
    assert [s.key for s in specs] == ["10", "9", "8"]


def test_select_pages_is_deterministic(tmp_path):
    db = _db(tmp_path)
    for c in range(1, 4):
        for i in range(5):
            db.add_note(f"c{c}n{i}", f"c{c}/{i}.md", pagerank=0.1 * c, community_id=c)
    first = [s.wiki_relpath for s in select_pages(db, min_community_size=5)]
    second = [s.wiki_relpath for s in select_pages(db, min_community_size=5)]
    assert first == second


def _spec(**kw):
    base = dict(kind="topic", key="7", wiki_relpath="topics/flame.md",
                title="The Sacred Flame", source_relpaths=["a.md", "b.md"])
    base.update(kw)
    return PageSpec(**base)


def test_build_mission_prompt_embeds_openwiki_rules(tmp_path):
    (tmp_path / "a.md").write_text("Note A about the flame. [[b]]", encoding="utf-8")
    (tmp_path / "b.md").write_text("Note B.", encoding="utf-8")
    prompt = build_mission_prompt(_spec(), tmp_path, existing_page=None)
    lowered = prompt.lower()
    assert "never invent" in lowered
    assert "[[wikilink" in lowered or "[[source" in lowered
    assert "thin page" in lowered
    assert "The Sacred Flame" in prompt
    assert "Note A about the flame" in prompt              # grounding excerpt present
    assert "SURGICAL" not in prompt                         # create mode, not update


def test_build_mission_prompt_surgical_mode_when_existing(tmp_path):
    (tmp_path / "a.md").write_text("Fresh content.", encoding="utf-8")
    (tmp_path / "b.md").write_text("More.", encoding="utf-8")
    existing = "---\ngenerated_by: legion-wiki\n---\nOld body [[a]]"
    prompt = build_mission_prompt(_spec(), tmp_path, existing_page=existing)
    assert "SURGICAL" in prompt
    assert "Old body [[a]]" in prompt                       # current page shown for diffing


def test_build_mission_prompt_trims_to_excerpt_budget(tmp_path):
    (tmp_path / "a.md").write_text("A" * 50_000, encoding="utf-8")
    (tmp_path / "b.md").write_text("B" * 50_000, encoding="utf-8")
    prompt = build_mission_prompt(_spec(), tmp_path, existing_page=None,
                                  excerpt_budget=1000)
    assert prompt.count("A") + prompt.count("B") <= 1000 + 50  # grounding trimmed
