# tests/test_vg_wiki_writer.py
import fcntl
import importlib.util
import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

from obsidian_legion.vaultgraph import wiki_writer as wiki_writer_mod
from obsidian_legion.vaultgraph.missions import PageSpec
from obsidian_legion.vaultgraph.wiki_writer import WikiWriter


def _load_nightly():
    path = Path(__file__).resolve().parents[1] / "scripts" / "legion_nightly.py"
    spec = importlib.util.spec_from_file_location("legion_nightly", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def _wire_community(db, community, n):
    """Semantic star among a community's members so it clears the R5 v2
    coherence gate (missions.select_pages, coherence_threshold=0.5)."""
    conn = sqlite3.connect(db.db_path)
    for i in range(1, n):
        conn.execute(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (?,?,?,1.0)",
            (f"c{community}n0", f"c{community}n{i}", "semantic"))
    conn.commit()
    conn.close()


def one_topic_db(vault, community=1, n=5):
    db = FakeGraphDB(vault / ".legion" / "graph.sqlite")
    for i in range(n):
        rel = f"notes/{community}_{i}.md"
        (vault / "notes").mkdir(exist_ok=True)
        (vault / rel).write_text(f"Body of note {i}. Mentions the flame.", encoding="utf-8")
        db.add_note(f"c{community}n{i}", rel, pagerank=0.5, community_id=community)
    _wire_community(db, community, n)
    return db


def VALID_BODY(title="Test Page", link="[[daily/note.md]]", words=130,
               see_also=None):
    """A v2-valid mission body: authored H1, lead paragraph, two ## sections
    citing a wikilink, padded to `words` whitespace tokens, and an optional
    '## See also' block built from wiki relpaths."""
    lines = [
        f"# {title}",
        "",
        "This encyclopedic page synthesizes its subject across sources "
        f"such as {link} and adjacent notes.",
        "",
        "## Origins",
        "",
        "The material is documented across several grounded notes in the vault.",
        "",
        "## Details",
        "",
        "Further analysis connects the subject to neighbouring topics.",
    ]
    text = "\n".join(lines)
    pad = words - len(text.split())
    if pad > 0:
        text += "\n\n" + " ".join(["context"] * pad)
    if see_also:
        text += "\n\n## See also\n\n" + "\n".join(
            f"- [[wiki/{rel}|{rel}]]" for rel in see_also)
    return text


def v2_page(body, provider="fake"):
    """Wrap a body in valid v2 frontmatter (all nine _FRONTMATTER_KEYS)."""
    return (
        "---\n"
        "generated_by: legion-wiki\n"
        'title: "Test Page"\n'
        'page_id: "topic:notes/a.md"\n'
        "sources:\n"
        "  - notes/a.md\n"
        'community_id: "1"\n'
        "updated_at: 2026-07-10T00:00:00+00:00\n"
        "mission_hash: abc123\n"
        "template_version: v2-encyclo-1\n"
        f"provider: {provider}\n"
        "---\n\n"
    ) + body


GOOD_BODY = VALID_BODY()   # v2-valid; existing FakeChain(GOOD_BODY) sites keep working


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
        _wire_community(db, c, 5)
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


def test_update_skips_when_graph_lock_held(tmp_path):
    # Spec §4.6: the wiki phase takes the SAME lock as the graph writer, so it
    # cannot run concurrently with an in-progress graph rebuild.
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    lock = open(vault / ".legion" / ".lock", "w")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        report = WikiWriter(vault, db, FakeChain(GOOD_BODY)).update(bootstrap=True)
        assert report == {"skipped": "already_running", "noop": True}
        assert not (vault / "wiki").exists()                     # nothing written
        assert not (vault / ".legion" / "wiki-state.json").exists()
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def test_nightly_skips_wiki_when_graph_skipped():
    nightly = _load_nightly()
    run, reason = nightly.should_run_wiki({"skipped": "already_running"})
    assert run is False and reason == "already_running"
    run_ok, reason_ok = nightly.should_run_wiki(
        {"notes_seen": 3, "changed": 1, "qdrant_ok": True})
    assert run_ok is True and reason_ok is None


def test_wall_clock_budget_defers_remaining(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    db = FakeGraphDB(vault / ".legion" / "graph.sqlite")
    (vault / "notes").mkdir()
    for c in range(1, 4):                               # 3 qualifying communities
        for i in range(5):
            rel = f"notes/{c}_{i}.md"
            (vault / rel).write_text(f"Note {c}.{i} flame. [[notes/{c}_0.md]]",
                                     encoding="utf-8")
            db.add_note(f"c{c}n{i}", rel, pagerank=float(c), community_id=c)
        _wire_community(db, c, 5)

    # started=0, page-1 check=0 (proceeds), page-2 check=5000 (over budget -> stop)
    ticks = iter([0.0, 0.0, 5000.0])
    last = [0.0]

    def fake_monotonic():
        try:
            last[0] = next(ticks)
        except StopIteration:
            pass
        return last[0]

    monkeypatch.setattr(time, "monotonic", fake_monotonic)
    report = WikiWriter(vault, db, FakeChain(GOOD_BODY)).update(budget=25, max_wall_s=1800)

    assert report["wall_clock_stop"] is True
    assert report["pages_written"] == 1
    assert report["pages_deferred"] == 2
    pages = list((vault / "wiki" / "topics").glob("*.md"))
    assert len(pages) == 1                              # only the first page written
    state = json.loads((vault / ".legion" / "wiki-state.json").read_text())
    assert len(state) == 1                             # state consistent with disk


def test_pages_written_atomically(tmp_path, monkeypatch):
    # No stray temp files left behind; a real write goes through os.replace.
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    replaced = []
    real_replace = wiki_writer_mod.os.replace

    def spy_replace(src, dst):
        replaced.append(Path(dst).name)
        return real_replace(src, dst)

    monkeypatch.setattr(wiki_writer_mod.os, "replace", spy_replace)
    report = WikiWriter(vault, db, FakeChain(GOOD_BODY)).update(bootstrap=True)
    assert report["pages_written"] == 1
    assert any(name.endswith(".md") for name in replaced)   # page via os.replace
    assert "index.md" in replaced                           # index via os.replace
    leftovers = list((vault / "wiki" / "topics").glob("*.tmp*")) + \
        list((vault / "wiki").glob("*.tmp*"))
    assert leftovers == []


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


def test_is_generated_marker_is_anchored(tmp_path):
    from obsidian_legion.vaultgraph.wiki_writer import _is_generated
    assert _is_generated("---\ngenerated_by: legion-wiki\n---\nbody") is True
    # bake-off pages must NOT be treated as legion-wiki pages
    assert _is_generated("---\ngenerated_by: vexpedia-bakeoff\n---\nb") is False
    # a superstring value must not match either (the v1 substring bug)
    assert _is_generated("---\ngenerated_by: legion-wiki-bakeoff\n---\nb") is False


def test_reset_leaves_non_generated_pages_alone(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    writer = WikiWriter(vault, db, FakeChain(VALID_BODY()))
    writer.update(bootstrap=True)
    topics = vault / "wiki" / "topics"
    decoy_bakeoff = topics / "_decoy_bakeoff.md"
    decoy_bakeoff.write_text(
        "---\ngenerated_by: vexpedia-bakeoff\ntitle: \"x\"\n---\n# X\n\n[[a.md]]",
        encoding="utf-8")
    decoy_superstring = topics / "_decoy_superstring.md"
    decoy_superstring.write_text(
        "---\ngenerated_by: legion-wiki-bakeoff\n---\n# Y\n\n[[a.md]]",
        encoding="utf-8")
    result = writer.reset()
    assert result["pages_removed"] >= 1          # the real generated page went
    assert decoy_bakeoff.exists()                # bake-off marker survives
    assert decoy_superstring.exists()            # superstring marker survives
