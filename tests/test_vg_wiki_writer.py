# tests/test_vg_wiki_writer.py
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from obsidian_legion.vaultgraph.missions import PageSpec
from obsidian_legion.vaultgraph.wiki_writer import WikiWriter


class FakeChain:
    """Provider chain stand-in. Returns canned bodies; scriptable per call."""

    def __init__(self, bodies, preflight=None):
        # bodies: str (repeat) or list[str] (consumed in order, last repeats)
        self._bodies = bodies
        self._i = 0
        self._preflight = preflight if preflight is not None else {"fake": True}
        self.dead_providers = set()
        self.prompts = []

    def preflight(self):
        return dict(self._preflight)

    def run_mission(self, prompt):
        self.prompts.append(prompt)
        if isinstance(self._bodies, str):
            body = self._bodies
        else:
            body = self._bodies[min(self._i, len(self._bodies) - 1)]
            self._i += 1
        if body is None:
            return SimpleNamespace(text="", provider="", ok=False,
                                   quota_exhausted=False, error="down")
        return SimpleNamespace(text=body, provider="fake", ok=True,
                               quota_exhausted=False, error="")


def make_vault(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".legion").mkdir(parents=True)
    return vault


class FakeGraphDB:
    def __init__(self, db_path):
        self.db_path = db_path
        conn = sqlite3.connect(db_path)
        conn.executescript(
            "CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, title TEXT, "
            "canonical_key TEXT, path TEXT, mtime REAL, sha256 TEXT, "
            "community_id INTEGER, centrality REAL, pagerank REAL, absent_since REAL);"
            "CREATE TABLE edges (src TEXT, dst TEXT, kind TEXT, weight REAL, annotation TEXT);"
            "CREATE TABLE communities (community_id INTEGER PRIMARY KEY, name TEXT, "
            "size INTEGER, top_members_json TEXT);")
        conn.commit()
        conn.close()

    def add_note(self, node_id, path, pagerank, community_id):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO nodes (id, kind, title, canonical_key, path, pagerank, "
            "community_id, absent_since) VALUES (?,?,?,?,?,?,?,NULL)",
            (node_id, "note", path, path.lower(), path, pagerank, community_id))
        conn.commit()
        conn.close()


def one_topic_db(vault, community=1, n=5):
    db = FakeGraphDB(vault / ".legion" / "graph.sqlite")
    for i in range(n):
        rel = f"notes/{community}_{i}.md"
        (vault / "notes").mkdir(exist_ok=True)
        (vault / rel).write_text(f"Body of note {i}. Mentions the flame.", encoding="utf-8")
        db.add_note(f"c{community}n{i}", rel, pagerank=0.5, community_id=community)
    return db


GOOD_BODY = "## Overview\nThe flame matters. See [[notes/1_0.md]] for detail."


def test_bootstrap_writes_pages_and_index(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    writer = WikiWriter(vault, db, FakeChain(GOOD_BODY))
    report = writer.update(bootstrap=True, bootstrap_cap=150)
    assert report["pages_written"] == 1
    assert report["noop"] is False
    pages = list((vault / "wiki" / "topics").glob("*.md"))
    assert pages and "generated_by: legion-wiki" in pages[0].read_text()
    assert (vault / "wiki" / "index.md").exists()
    assert "fake" in report["provider_fates"]


def test_validate_page_rules(tmp_path):
    vault = make_vault(tmp_path)
    writer = WikiWriter(vault, one_topic_db(vault), FakeChain(GOOD_BODY))
    good = ("---\ngenerated_by: legion-wiki\nsources:\n  - a.md\ncommunity_id: \"1\"\n"
            "updated_at: x\nmission_hash: abc\n---\nBody with [[a.md]].")
    assert writer.validate_page(good) is True
    assert writer.validate_page(good.replace("mission_hash: abc\n", "")) is False
    assert writer.validate_page("---\ngenerated_by: legion-wiki\nsources: a\n"
                                "community_id: \"1\"\nupdated_at: x\nmission_hash: y\n"
                                "---\nNo wikilink here.") is False
    assert writer.validate_page("") is False


def test_second_run_is_noop_and_writes_nothing(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    writer = WikiWriter(vault, db, FakeChain(GOOD_BODY))
    writer.update(bootstrap=True)
    index = vault / "wiki" / "index.md"
    before = index.stat().st_mtime_ns
    page = next((vault / "wiki" / "topics").glob("*.md"))
    page_before = page.stat().st_mtime_ns
    report = WikiWriter(vault, db, FakeChain(GOOD_BODY)).update()
    assert report["noop"] is True
    assert report["pages_written"] == 0
    assert index.stat().st_mtime_ns == before          # index untouched
    assert page.stat().st_mtime_ns == page_before        # page untouched


def test_changed_source_regenerates_page(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    WikiWriter(vault, db, FakeChain(GOOD_BODY)).update(bootstrap=True)
    (vault / "notes" / "1_0.md").write_text("CHANGED body. [[notes/1_1.md]]",
                                            encoding="utf-8")
    report = WikiWriter(vault, db, FakeChain(GOOD_BODY)).update()
    assert report["pages_written"] == 1
    assert report["noop"] is False


def test_out_of_band_deleted_page_regenerates(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    WikiWriter(vault, db, FakeChain(GOOD_BODY)).update(bootstrap=True)
    page = next((vault / "wiki" / "topics").glob("*.md"))
    page.unlink()                                        # deleted out of band
    report = WikiWriter(vault, db, FakeChain(GOOD_BODY)).update()
    assert report["pages_written"] == 1
    assert page.exists()


def test_blocklist_from_wikiignore_pages_section(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    # discover the page path first
    probe = WikiWriter(vault, db, FakeChain(GOOD_BODY))
    from obsidian_legion.vaultgraph.missions import select_pages
    page_rel = select_pages(db)[0].wiki_relpath
    (vault / ".wikiignore").write_text(
        "# public export filters\nraw/private-*\n# pages\n" + page_rel + "\n",
        encoding="utf-8")
    report = probe.update(bootstrap=True)
    assert report["pages_written"] == 0                 # blocklisted -> never generated
    assert not (vault / "wiki" / page_rel).exists()


def test_budget_defers_extra_pages(tmp_path):
    vault = make_vault(tmp_path)
    db = FakeGraphDB(vault / ".legion" / "graph.sqlite")
    (vault / "notes").mkdir()
    for c in range(1, 4):                               # 3 qualifying communities
        for i in range(5):
            rel = f"notes/{c}_{i}.md"
            (vault / rel).write_text(f"Note {c}.{i} flame. [[notes/{c}_0.md]]",
                                     encoding="utf-8")
            db.add_note(f"c{c}n{i}", rel, pagerank=float(c), community_id=c)
    report = WikiWriter(vault, db, FakeChain(GOOD_BODY)).update(budget=1)
    assert report["pages_written"] == 1
    assert report["pages_deferred"] == 2


def test_invalid_output_retries_once_then_skips(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    thin = "No wikilink and thus invalid."               # fails validation both times
    report = WikiWriter(vault, db, FakeChain(thin)).update(bootstrap=True)
    assert report["pages_written"] == 0
    assert report["pages_failed"] == 1


def test_reset_removes_generated_pages(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    writer = WikiWriter(vault, db, FakeChain(GOOD_BODY))
    writer.update(bootstrap=True)
    result = writer.reset()
    assert result["pages_removed"] >= 1
    assert not list((vault / "wiki" / "topics").glob("*.md"))
    assert (vault / ".legion" / "wiki-state.json").exists()   # state kept without --regenerate


def test_reset_regenerate_also_wipes_state(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    writer = WikiWriter(vault, db, FakeChain(GOOD_BODY))
    writer.update(bootstrap=True)
    result = writer.reset(regenerate=True)
    assert result["state_removed"] is True
    assert not (vault / ".legion" / "wiki-state.json").exists()


def test_write_index_is_deterministic(tmp_path):
    vault = make_vault(tmp_path)
    writer = WikiWriter(vault, one_topic_db(vault), FakeChain(GOOD_BODY))
    specs = [PageSpec("topic", "1", "topics/b.md", "Beta", ["x.md"]),
             PageSpec("entity", "n1", "entities/a.md", "Alpha", ["y.md"])]
    first = writer.write_index(specs).read_text()
    second = writer.write_index(specs).read_text()
    assert first == second
    assert "Topics" in first and "Entities" in first
    assert "Alpha" in first and "Beta" in first
