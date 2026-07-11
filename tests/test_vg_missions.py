# tests/test_vg_missions.py
import sqlite3
from pathlib import Path

from obsidian_legion.vaultgraph.missions import (
    PageSpec, build_mission_prompt, select_pages, _fair_share,
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

    def add_semantic(self, src, dst, weight=1.0):
        self._exec("INSERT INTO edges (src, dst, kind, weight) VALUES (?,?,?,?)",
                   (src, dst, "semantic", weight))

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
    for i in range(1, 5):
        db.add_semantic("c1n0", f"c1n{i}")                 # star -> coherent
    # community 2: 6 notes, mean pagerank 0.5 -> score 3.0 (ranks first)
    for i in range(6):
        db.add_note(f"c2n{i}", f"c2/{i}.md", 0.5, community_id=2)
    for i in range(1, 6):
        db.add_semantic("c2n0", f"c2n{i}")
    # community 3: 4 notes -> below min_community_size, dropped
    for i in range(4):
        db.add_note(f"c3n{i}", f"c3/{i}.md", 0.9, community_id=3)
    specs = select_pages(db, min_community_size=5, pagerank_percentile=99.9)
    topics = [s for s in specs if s.kind == "topic"]
    assert [s.key for s in topics] == ["2", "1"]           # higher score first
    # v2: title/slug/page_id derive from the anchor (top-PageRank member note),
    # not a TF-IDF community name.
    assert topics[0].title == "c2/0.md"
    assert topics[0].page_id == "topic:c2/0.md"
    # _slug("c2/0.md") == "c2-0-md" — a path-derived title keeps its "-md"
    # tail in the slug (pre-flight scan fix: was wrongly "topics/c2-0.md").
    assert topics[0].wiki_relpath == "topics/c2-0-md.md"
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
        for i in range(1, 5):
            db.add_semantic(f"c{c}n0", f"c{c}n{i}")         # star -> coherent
    report = {}
    specs = select_pages(db, max_pages=3, min_community_size=5,
                         pagerank_percentile=99.9, selection_report=report)
    assert len(specs) == 3
    # deterministic: highest size*mean_pagerank first (community 10, 9, 8)
    assert [s.key for s in specs] == ["10", "9", "8"]
    assert report["selection_truncated"] == 7              # 10 candidates - 3 kept
    assert report["skipped_incoherent"] == []


def test_select_pages_is_deterministic(tmp_path):
    db = _db(tmp_path)
    for c in range(1, 4):
        for i in range(5):
            db.add_note(f"c{c}n{i}", f"c{c}/{i}.md", pagerank=0.1 * c, community_id=c)
        for i in range(1, 5):
            db.add_semantic(f"c{c}n0", f"c{c}n{i}")
    first = [s.wiki_relpath for s in select_pages(db, min_community_size=5)]
    second = [s.wiki_relpath for s in select_pages(db, min_community_size=5)]
    assert first == second
    assert first                                            # coherent -> non-empty


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
    assert "never invent" in lowered                       # v1 grounding kept
    assert "[[wikilink" in lowered or "[[source" in lowered
    assert "synthesize" in lowered                         # v2 rule 4
    assert "see also" in lowered                            # v2 rules 3 & 6
    assert "The Sacred Flame" in prompt
    assert "Note A about the flame" in prompt               # grounding excerpt present
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


# --- fair-share water-filling (R5 v2 §5.3) ---------------------------------

def test_fair_share_normative_example():
    # water-filling: share = 60000 // 4 = 15000 -> 500 and 200 satisfied
    #   (remaining 59300); next share = 59300 // 2 = 29650 satisfies nobody,
    #   so both long sources get 29650 each; residue 59300 - 29650*2 = 0.
    assert _fair_share([500, 40000, 40000, 200], 60000) == [500, 29650, 29650, 200]


def test_fair_share_empty():
    assert _fair_share([], 60000) == []


def test_fair_share_single_source():
    # one source shorter than the whole budget is satisfied at its length
    assert _fair_share([100], 60000) == [100]


def test_fair_share_all_tiny_sources_under_budget():
    # sum(10+20+30) = 60 <= 1000 ; every source satisfied at its length,
    # the leftover budget is simply never handed out.
    result = _fair_share([10, 20, 30], 1000)
    assert result == [10, 20, 30]
    assert sum(result) <= 1000


def test_fair_share_residue_goes_to_first():
    # 3 long sources, none satisfiable by the equal share:
    #   share = 20000 // 3 = 6666 ; residue = 20000 - 6666*3 = 20000 - 19998 = 2
    #   residue (< n_remaining = 3) goes to the FIRST (highest-PageRank) source.
    result = _fair_share([10000, 10000, 10000], 20000)
    assert result == [6668, 6666, 6666]
    assert sum(result) <= 20000


# --- prompt v2: RELATED PAGES + fair-share grounding -----------------------

def test_build_mission_prompt_includes_related_pages_when_candidates_present(tmp_path):
    (tmp_path / "a.md").write_text("Note A. [[b]]", encoding="utf-8")
    (tmp_path / "b.md").write_text("Note B.", encoding="utf-8")
    spec = _spec(related_candidates=[("topics/foo.md", "Foo"),
                                     ("entities/bar.md", "Bar")])
    prompt = build_mission_prompt(spec, tmp_path, existing_page=None)
    assert "## RELATED PAGES (candidates for See also):" in prompt
    assert "- [[wiki/topics/foo.md|Foo]]" in prompt
    assert "- [[wiki/entities/bar.md|Bar]]" in prompt


def test_build_mission_prompt_omits_related_pages_when_no_candidates(tmp_path):
    (tmp_path / "a.md").write_text("Note A.", encoding="utf-8")
    (tmp_path / "b.md").write_text("Note B.", encoding="utf-8")
    prompt = build_mission_prompt(_spec(), tmp_path, existing_page=None)
    # The candidate BLOCK is omitted; the phrase "RELATED PAGES" still occurs in
    # the always-present MISSION_RULES (rule 6) and TASK prose, so guard on the
    # exact block header (the negation of the positive test's assertion).
    assert "## RELATED PAGES (candidates for See also):" not in prompt


def test_build_mission_prompt_fair_share_keeps_later_sources(tmp_path):
    # A 100k-char first note is truncated to its fair share, but the short
    # second source survives in full (v1's PageRank-order fill would starve it).
    (tmp_path / "a.md").write_text("A" * 100_000, encoding="utf-8")
    (tmp_path / "b.md").write_text("Bravo distinctive marker content.", encoding="utf-8")
    prompt = build_mission_prompt(_spec(), tmp_path, existing_page=None,
                                  excerpt_budget=60000)
    assert prompt.count("A") < 100_000                     # first source truncated
    assert "Bravo distinctive marker content." in prompt   # second source intact


# --- selection v2: anchors, coherence gate, collisions, candidates ---------

def test_topic_anchor_page_id_and_slug_from_anchor_title(tmp_path):
    db = _db(tmp_path)
    # anchor = highest-PageRank member; its title drives slug + page_id
    db.add_note("hub", "projects/docker.md", 0.9, community_id=1, title="Docker Phoenix")
    for i in range(4):
        db.add_note(f"m{i}", f"notes/{i}.md", 0.1, community_id=1, title=f"Member {i}")
        db.add_semantic("hub", f"m{i}")
    specs = select_pages(db, min_community_size=5, pagerank_percentile=99.9)
    topic = next(s for s in specs if s.kind == "topic")
    assert topic.title == "Docker Phoenix"
    assert topic.wiki_relpath == "topics/docker-phoenix.md"
    assert topic.page_id == "topic:projects/docker.md"
    assert topic.key == "1"


def test_coherence_gate_skips_incoherent_community(tmp_path):
    db = _db(tmp_path)
    db.add_note("a0", "junk/castle.md", 0.9, community_id=1, title="Castle")
    for i in range(1, 5):
        db.add_note(f"a{i}", f"junk/{i}.md", 0.1, community_id=1, title=f"Junk {i}")
    # no semantic/wikilink edge among members -> fraction 0 < 0.5 -> skipped
    report = {}
    specs = select_pages(db, min_community_size=5, pagerank_percentile=99.9,
                         selection_report=report)
    assert [s for s in specs if s.kind == "topic"] == []
    assert "castle" in report["skipped_incoherent"]        # would-be slug reported


def test_coherence_gate_counts_undirected_adjacency(tmp_path):
    db = _db(tmp_path)
    # ONLY hub->member rows exist. An undirected reading must still count each
    # member as connected (hub is its neighbor); a src-only reading would give
    # each member 0 neighbors -> fraction 1/5 = 0.2 < 0.5 and wrongly skip.
    db.add_note("hub", "topics/hub.md", 0.9, community_id=1, title="Hub")
    for i in range(4):
        db.add_note(f"m{i}", f"notes/{i}.md", 0.1, community_id=1, title=f"M{i}")
        db.add_semantic("hub", f"m{i}")                    # hub -> m{i} only
    report = {}
    specs = select_pages(db, min_community_size=5, pagerank_percentile=99.9,
                         selection_report=report)
    assert any(s.kind == "topic" for s in specs)
    assert report["skipped_incoherent"] == []


def test_wikilink_only_community_passes_coherence(tmp_path):
    db = _db(tmp_path)
    db.add_note("w0", "topics/w0.md", 0.9, community_id=1, title="W0")
    for i in range(1, 5):
        db.add_note(f"w{i}", f"notes/{i}.md", 0.1, community_id=1, title=f"W{i}")
        db.add_wikilink("w0", f"w{i}")                     # wikilink edges only
    specs = select_pages(db, min_community_size=5, pagerank_percentile=99.9)
    assert any(s.kind == "topic" for s in specs)           # wikilinks count


def test_coherence_threshold_boundary_half_passes(tmp_path):
    db = _db(tmp_path)
    for i in range(4):
        db.add_note(f"m{i}", f"notes/{i}.md", 0.5, community_id=1, title=f"M{i}")
    db.add_semantic("m0", "m1")                            # exactly 2 of 4 connected
    specs = select_pages(db, min_community_size=4, pagerank_percentile=99.9)
    assert any(s.kind == "topic" for s in specs)           # fraction 0.5 >= threshold 0.5


def test_cross_kind_slug_collision_suffixed(tmp_path):
    db = _db(tmp_path)
    # topic "Foo" from a coherent community
    db.add_note("t0", "proj/foo.md", 0.9, community_id=1, title="Foo")
    for i in range(1, 5):
        db.add_note(f"t{i}", f"proj/{i}.md", 0.1, community_id=1, title=f"T{i}")
        db.add_semantic("t0", f"t{i}")
    # entity "Foo": a high-PageRank note outside any qualifying community
    db.add_note("e0", "people/foo.md", 5.0, title="Foo")
    specs = select_pages(db, min_community_size=5, pagerank_percentile=90.0)
    foos = [s for s in specs if s.title == "Foo"]
    assert len(foos) == 2
    assert {s.kind for s in foos} == {"topic", "entity"}
    # one slug namespace across both kinds: topic (selected first) keeps 'foo',
    # the entity gets '-2' in its own directory -> distinct relpaths, no drop.
    assert sorted(s.wiki_relpath for s in foos) == ["entities/foo-2.md", "topics/foo.md"]


def test_related_candidates_rank_shared_sources_and_zero_overlap(tmp_path):
    db = _db(tmp_path)
    # Two coherent communities that share one source note path (distinct node
    # ids, identical path) -> each lists the other in related_candidates.
    db.add_note("A0", "shared/common.md", 0.9, community_id=1, title="Alpha")
    for i in range(1, 5):
        db.add_note(f"A{i}", f"a/{i}.md", 0.1, community_id=1, title=f"A{i}")
        db.add_semantic("A0", f"A{i}")
    db.add_note("B0", "shared/common.md", 0.9, community_id=2, title="Beta")
    for i in range(1, 5):
        db.add_note(f"B{i}", f"b/{i}.md", 0.1, community_id=2, title=f"B{i}")
        db.add_semantic("B0", f"B{i}")
    # A third coherent community sharing nothing -> zero-overlap page gets []
    db.add_note("C0", "c/0.md", 0.9, community_id=3, title="Gamma")
    for i in range(1, 5):
        db.add_note(f"C{i}", f"c/{i}.md", 0.1, community_id=3, title=f"C{i}")
        db.add_semantic("C0", f"C{i}")
    specs = select_pages(db, min_community_size=5, pagerank_percentile=99.9)
    by_key = {s.key: s for s in specs if s.kind == "topic"}
    alpha, beta, gamma = by_key["1"], by_key["2"], by_key["3"]
    assert (beta.wiki_relpath, beta.title) in alpha.related_candidates
    assert (alpha.wiki_relpath, alpha.title) in beta.related_candidates
    assert gamma.related_candidates == []


def test_related_candidates_capped_at_related_cap(tmp_path):
    from obsidian_legion.vaultgraph.missions import _RELATED_CAP
    db = _db(tmp_path)
    # 10 coherent communities all sharing one common source path: the first
    # page overlaps 9 others but keeps at most _RELATED_CAP candidates.
    for c in range(1, 11):
        db.add_note(f"H{c}", "shared/common.md", 0.9, community_id=c, title=f"Hub{c}")
        for i in range(1, 5):
            db.add_note(f"C{c}n{i}", f"c{c}/{i}.md", 0.1, community_id=c, title=f"C{c}m{i}")
            db.add_semantic(f"H{c}", f"C{c}n{i}")
    specs = select_pages(db, min_community_size=5, pagerank_percentile=99.9)
    topic = next(s for s in specs if s.kind == "topic")
    assert len(topic.related_candidates) == _RELATED_CAP   # 9 overlaps -> capped at 8
