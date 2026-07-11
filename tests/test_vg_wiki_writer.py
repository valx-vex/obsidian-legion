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


def _generated_page(title, page_id, body="Body with a [[wiki/topics/x.md|X]] link."):
    return (
        "---\n"
        "generated_by: legion-wiki\n"
        f'title: "{title}"\n'
        f'page_id: "{page_id}"\n'
        "sources:\n"
        "  - notes/x.md\n"
        'community_id: ""\n'
        "updated_at: 2026-07-10T00:00:00\n"
        "mission_hash: deadbeef\n"
        "template_version: v2-encyclo-1\n"
        "provider: fake\n"
        "---\n"
        f"# {title}\n\n{body}\n"
    )


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
    writer = WikiWriter(vault, one_topic_db(vault), FakeChain(VALID_BODY()))
    good = v2_page(VALID_BODY())
    assert writer.validate_page(good, kind="topic", n_sources=1) is True
    # a missing frontmatter key (drop template_version) -> invalid
    assert writer.validate_page(
        good.replace("template_version: v2-encyclo-1\n", ""),
        kind="topic", n_sources=1) is False
    # body without any wikilink -> invalid
    assert writer.validate_page(
        v2_page("# Title\n\nProse with no wikilink at all here."),
        kind="topic", n_sources=1) is False
    # empty text -> invalid
    assert writer.validate_page("") is False


def test_validate_page_v2_rejects_corruption_and_bad_h1(tmp_path):
    vault = make_vault(tmp_path)
    writer = WikiWriter(vault, one_topic_db(vault), FakeChain(VALID_BODY()))
    good = v2_page(VALID_BODY())
    assert writer.validate_page(good, kind="topic", n_sources=1) is True
    # residual ESC byte anywhere in the text
    assert writer.validate_page(good + "\x1b", kind="topic", n_sources=1) is False
    # <think> reasoning span
    assert writer.validate_page(
        v2_page(VALID_BODY() + "\n\n<think>internal</think>"),
        kind="topic", n_sources=1) is False
    # gpt-oss 'Thinking...' line
    assert writer.validate_page(
        v2_page("# T\n\nThinking...\nlead with [[a.md]] and words."),
        kind="topic", n_sources=1) is False
    # gpt-oss '...done thinking.' line
    assert writer.validate_page(
        v2_page("# T\n\nsummary ...done thinking.\nlead [[a.md]] words."),
        kind="topic", n_sources=1) is False
    # missing H1 (first body line is prose)
    assert writer.validate_page(
        v2_page("Just prose with [[a.md]] and no heading."),
        kind="topic", n_sources=1) is False
    # H1 containing [[
    assert writer.validate_page(
        v2_page("# Title [[x]]\n\nlead [[a.md]] words."),
        kind="topic", n_sources=1) is False
    # H1 containing |
    assert writer.validate_page(
        v2_page("# Title | Sub\n\nlead [[a.md]] words."),
        kind="topic", n_sources=1) is False
    # H1 containing a backtick
    assert writer.validate_page(
        v2_page("# Title `code`\n\nlead [[a.md]] words."),
        kind="topic", n_sources=1) is False


def test_validate_see_also_required_iff_candidates(tmp_path):
    vault = make_vault(tmp_path)
    writer = WikiWriter(vault, one_topic_db(vault), FakeChain(VALID_BODY()))
    no_sa = v2_page(VALID_BODY())
    with_sa = v2_page(VALID_BODY(see_also=["topics/other.md"]))
    # candidates provided -> a See also section with a wiki link is mandatory
    assert writer.validate_page(no_sa, kind="topic", n_sources=1,
                                candidates_provided=True) is False
    assert writer.validate_page(with_sa, kind="topic", n_sources=1,
                                candidates_provided=True) is True
    # no candidates -> the section is waived
    assert writer.validate_page(no_sa, kind="topic", n_sources=1,
                                candidates_provided=False) is True


def test_validate_page_v2_word_floors(tmp_path):
    vault = make_vault(tmp_path)
    writer = WikiWriter(vault, one_topic_db(vault), FakeChain(VALID_BODY()))
    # topic with >=5 sources under 120 words -> reject
    assert writer.validate_page(v2_page(VALID_BODY(words=100)),
                                kind="topic", n_sources=5) is False
    assert writer.validate_page(v2_page(VALID_BODY(words=130)),
                                kind="topic", n_sources=5) is True
    # entity under 60 words -> reject
    assert writer.validate_page(v2_page(VALID_BODY(words=50)),
                                kind="entity", n_sources=1) is False
    assert writer.validate_page(v2_page(VALID_BODY(words=70)),
                                kind="entity", n_sources=1) is True


def test_compose_quotes_title_with_colon_and_writes_v2_keys(tmp_path):
    vault = make_vault(tmp_path)
    writer = WikiWriter(vault, one_topic_db(vault), FakeChain(VALID_BODY()))
    spec = PageSpec("topic", "7", "topics/docker.md", "Docker Anchor",
                    ["notes/a.md"], page_id="topic:notes/a.md")
    body = VALID_BODY(title="Docker: from dev to prod")
    page = writer._compose(spec, {"notes/a.md": "sha"}, body, "minimax-m3:cloud")
    lines = page.splitlines()
    assert 'title: "Docker: from dev to prod"' in lines   # colon-safe, quoted
    assert 'page_id: "topic:notes/a.md"' in lines
    assert "template_version: v2-encyclo-1" in lines
    assert "provider: minimax-m3:cloud" in lines


def test_compose_fallback_title_prepends_h1(tmp_path):
    vault = make_vault(tmp_path)
    writer = WikiWriter(vault, one_topic_db(vault), FakeChain(VALID_BODY()))
    spec = PageSpec("topic", "1", "topics/x.md", "Fallback Anchor",
                    ["notes/a.md"], page_id="topic:notes/a.md")
    body = "This body has no level-one heading. See [[notes/a.md]]."
    page = writer._compose(spec, {"notes/a.md": "sha"}, body, "fake")
    assert 'title: "Fallback Anchor"' in page.splitlines()
    body_part = page.split("---")[2]
    first = [ln for ln in body_part.splitlines() if ln.strip()][0]
    assert first == "# Fallback Anchor"                    # H1 prepended


def test_generate_strips_reasoning_and_ansi_end_to_end(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    corrupted = ("\x1b[2K\x1b[K<think>internal reasoning here</think>\n"
                 "# Salvaged Title\n\n"
                 "The subject is grounded in [[notes/1_0.md]] and related "
                 "notes. " + "context " * 130)
    report = WikiWriter(vault, db, FakeChain(corrupted)).update(bootstrap=True)
    assert report["pages_written"] == 1
    page = next((vault / "wiki" / "topics").glob("*.md"))
    text = page.read_text()
    assert "\x1b" not in text
    assert "<think>" not in text.lower()
    assert "# Salvaged Title" in text
    assert 'title: "Salvaged Title"' in text


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


def test_should_run_wiki_allows_skip_graph_reason():
    nightly = _load_nightly()
    # A graph phase bypassed via --skip-graph presents a healthy report to the
    # wiki phase: the wiki MUST still run (R5 §8.3a).
    run, reason = nightly.should_run_wiki({"skipped": nightly.SKIP_GRAPH_REASON})
    assert run is True and reason is None
    # Lock-contention skip (another rebuild holds the lock) still blocks the
    # wiki phase — existing safety behavior preserved.
    blocked, why = nightly.should_run_wiki({"skipped": "already_running"})
    assert blocked is False and why == "already_running"


def test_nightly_skip_graph_runs_wiki_skip_wiki_skips(tmp_path, monkeypatch):
    import obsidian_legion.vaultgraph.builder as builder_mod
    import obsidian_legion.vaultgraph.graphdb as graphdb_mod
    import obsidian_legion.vaultgraph.providers as providers_mod
    import obsidian_legion.vaultgraph.wiki_writer as writer_mod
    from obsidian_legion.vaultgraph import report as report_mod

    nightly = _load_nightly()
    graph_calls = []
    wiki_calls = []

    class FakeBuilder:
        def __init__(self, root):
            graph_calls.append(root)

        def update(self):
            return {"notes_seen": 1, "changed": 0}

    class FakeWriter:
        def __init__(self, root, db, chain):
            self.root = root

        def update(self, budget=25, max_wall_s=1800):
            wiki_calls.append((budget, max_wall_s))
            return {"pages_written": 1, "pages_skipped": 0, "pages_deferred": 0,
                    "pages_failed": 0, "noop": False, "provider_fates": {}}

    class FakeChain:
        def __init__(self, providers):
            self.providers = providers

        def preflight(self):
            return {"ollama": True}

    class FakeDB:
        def __init__(self, path):
            self.path = path

    monkeypatch.setattr(nightly, "_resolve_vault",
                        lambda arg: ("testvault", tmp_path))
    monkeypatch.setattr(builder_mod, "GraphBuilder", FakeBuilder)
    monkeypatch.setattr(writer_mod, "WikiWriter", FakeWriter)
    monkeypatch.setattr(graphdb_mod, "GraphDB", FakeDB)
    monkeypatch.setattr(providers_mod, "ProviderChain", FakeChain)
    monkeypatch.setattr(providers_mod, "wiki_providers",
                        lambda: [{"name": "ollama", "kind": "http"}])
    monkeypatch.setattr(report_mod, "REPORT_DIR", tmp_path / "legion")

    # --skip-graph: graph phase bypassed, wiki phase runs.
    rc = nightly.main(["--skip-graph"])
    assert rc == 0
    assert graph_calls == []            # GraphBuilder never instantiated
    assert len(wiki_calls) == 1         # WikiWriter.update ran once

    # --skip-graph --skip-wiki: wiki phase does NOT run.
    wiki_calls.clear()
    rc2 = nightly.main(["--skip-graph", "--skip-wiki"])
    assert rc2 == 0
    assert graph_calls == []
    assert wiki_calls == []             # wiki skipped by --skip-wiki


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
    writer = WikiWriter(vault, FakeGraphDB(vault / ".legion" / "graph.sqlite"),
                        FakeChain(GOOD_BODY))
    topics = vault / "wiki" / "topics"
    entities = vault / "wiki" / "entities"
    topics.mkdir(parents=True)
    entities.mkdir(parents=True)
    (topics / "beta.md").write_text(_generated_page("Beta", "topic:beta"),
                                    encoding="utf-8")
    (entities / "alpha.md").write_text(_generated_page("Alpha", "entity:alpha"),
                                       encoding="utf-8")
    first = writer.write_index().read_text()
    second = writer.write_index().read_text()
    assert first == second
    assert "Topics" in first and "Entities" in first
    assert "Alpha" in first and "Beta" in first


def test_write_index_scans_disk_truth(tmp_path):
    vault = make_vault(tmp_path)
    writer = WikiWriter(vault, FakeGraphDB(vault / ".legion" / "graph.sqlite"),
                        FakeChain(GOOD_BODY))
    topics = vault / "wiki" / "topics"
    entities = vault / "wiki" / "entities"
    topics.mkdir(parents=True)
    entities.mkdir(parents=True)
    # disk truth: an orphan generated file (never referenced by state) still appears
    (topics / "orphan.md").write_text(
        _generated_page("Orphan Topic", "topic:orphan"), encoding="utf-8")
    (entities / "someone.md").write_text(
        _generated_page("Someone", "entity:someone"), encoding="utf-8")
    # YAML-quoted title with a colon + escaped inner quotes, and two sources
    (topics / "tricky.md").write_text(
        "---\ngenerated_by: legion-wiki\n"
        'title: "A: \\"quoted\\" title"\n'
        'page_id: "topic:tricky"\nsources:\n  - notes/a.md\n  - notes/b.md\n'
        'community_id: "2"\nupdated_at: x\nmission_hash: h\n'
        "template_version: v2-encyclo-1\nprovider: fake\n---\n# X\n\nBody [[wiki/z]].\n",
        encoding="utf-8")
    # a _bakeoff/ file must NOT appear (non-recursive glob + non-legion marker)
    bake = vault / "wiki" / "_bakeoff" / "m"
    bake.mkdir(parents=True)
    (bake / "orphan.md").write_text(
        '---\ngenerated_by: vexpedia-bakeoff\ntitle: "Bake"\n---\n# Bake\n',
        encoding="utf-8")
    # a non-generated hand-written .md must NOT appear
    (topics / "hand.md").write_text("# Hand written\n\nNope.\n", encoding="utf-8")

    text = writer.write_index().read_text(encoding="utf-8")
    assert "Orphan Topic" in text
    assert "Someone" in text
    assert "[[wiki/topics/orphan.md\\|Orphan Topic]]" in text
    assert 'A: "quoted" title' in text          # YAML title unescaped
    assert "| 2 |" in text                       # tricky page source count
    assert "Bake" not in text                    # _bakeoff excluded (non-recursive)
    assert "Hand written" not in text            # non-generated excluded
    assert text.index("orphan.md") < text.index("tricky.md")   # deterministic order


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


def test_state_is_keyed_by_page_id_and_records_provider(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    report = WikiWriter(vault, db, FakeChain(VALID_BODY())).update(bootstrap=True)
    assert report["pages_written"] == 1
    assert report["pages_by_provider"] == {"fake": 1}
    state = json.loads((vault / ".legion" / "wiki-state.json").read_text())
    assert len(state) == 1
    (page_id, entry), = state.items()
    assert page_id.startswith("topic:")
    assert entry["relpath"].startswith("topics/")
    assert entry["provider"] == "fake"
    assert "sources" in entry and "mission_hash" in entry and "updated_at" in entry


def test_report_merges_selection_report_keys(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    report = WikiWriter(vault, db, FakeChain(VALID_BODY())).update(bootstrap=True)
    assert report["skipped_incoherent"] == []
    assert report["selection_truncated"] == 0
    assert isinstance(report["skipped_incoherent"], list)
    assert isinstance(report["selection_truncated"], int)
    assert report["see_also_pruned"] == 0


def test_report_counts_stale_generated_pages(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)
    orphan = vault / "wiki" / "topics" / "orphan-stale.md"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("---\ngenerated_by: legion-wiki\ntitle: \"Orphan\"\n"
                      "page_id: \"topic:gone\"\n---\n# Orphan\n\nbody [[x.md]]",
                      encoding="utf-8")
    report = WikiWriter(vault, db, FakeChain(VALID_BODY())).update(bootstrap=True)
    assert report["pages_written"] == 1
    assert report["stale_pages"] == 1          # the orphan; the real page is in state


def test_relpath_migration_deletes_old_file_on_rename(tmp_path):
    vault = make_vault(tmp_path)
    db = one_topic_db(vault)                    # anchor id 'c1n0', path notes/1_0.md
    WikiWriter(vault, db, FakeChain(VALID_BODY())).update(bootstrap=True)
    old_page = next((vault / "wiki" / "topics").glob("*.md"))
    # rename the anchor's title -> new slug -> new relpath, SAME page_id
    conn = sqlite3.connect(db.db_path)
    conn.execute("UPDATE nodes SET title=? WHERE id=?", ("Renamed Anchor", "c1n0"))
    conn.commit()
    conn.close()
    report = WikiWriter(vault, db, FakeChain(VALID_BODY())).update()
    assert report["pages_written"] == 1
    assert not old_page.exists()                # old file migrated away
    new_pages = list((vault / "wiki" / "topics").glob("*.md"))
    assert len(new_pages) == 1
    assert new_pages[0].name == "renamed-anchor.md"
    state = json.loads((vault / ".legion" / "wiki-state.json").read_text())
    assert len(state) == 1                       # one entry, not two
    (page_id, entry), = state.items()
    assert page_id == "topic:notes/1_0.md"
    assert entry["relpath"] == "topics/renamed-anchor.md"


def test_reconcile_see_also_prunes_dead_keeps_live(tmp_path):
    vault = make_vault(tmp_path)
    writer = WikiWriter(vault, FakeGraphDB(vault / ".legion" / "graph.sqlite"),
                        FakeChain(GOOD_BODY))
    topics = vault / "wiki" / "topics"
    topics.mkdir(parents=True)
    (topics / "live.md").write_text(_generated_page("Live", "topic:live"),
                                    encoding="utf-8")   # See-also target that exists
    page = topics / "subject.md"
    page.write_text(
        "---\ngenerated_by: legion-wiki\n"
        'title: "Subject"\npage_id: "topic:subject"\nsources:\n  - notes/x.md\n'
        'community_id: "1"\nupdated_at: x\nmission_hash: h\n'
        "template_version: v2-encyclo-1\nprovider: fake\n---\n"
        "# Subject\n\nLead about [[wiki/topics/ghost.md|Ghost]] in body.\n\n"
        "## Details\n\nStuff.\n\n"
        "## See also\n\n"
        "- [[wiki/topics/live.md|Live]]\n"
        "- [[wiki/topics/dead.md|Dead]]\n",
        encoding="utf-8")
    result = writer.reconcile_see_also()
    text = page.read_text(encoding="utf-8")
    assert result == {"links_pruned": 1, "sections_removed": 0}
    assert "[[wiki/topics/live.md|Live]]" in text        # live link kept
    assert "dead.md" not in text                          # dead link removed
    assert "## See also" in text                          # section retained
    assert "[[wiki/topics/ghost.md|Ghost]]" in text       # body link untouched
    # idempotent second call
    assert writer.reconcile_see_also() == {"links_pruned": 0, "sections_removed": 0}
    assert page.read_text(encoding="utf-8") == text
    # atomic: no stray temp files left behind
    assert all(p.suffix == ".md" for p in topics.iterdir())


def test_reconcile_see_also_removes_emptied_section(tmp_path):
    vault = make_vault(tmp_path)
    writer = WikiWriter(vault, FakeGraphDB(vault / ".legion" / "graph.sqlite"),
                        FakeChain(GOOD_BODY))
    topics = vault / "wiki" / "topics"
    topics.mkdir(parents=True)
    page = topics / "subject.md"
    page.write_text(
        "---\ngenerated_by: legion-wiki\n"
        'title: "Subject"\npage_id: "topic:subject"\nsources:\n  - notes/x.md\n'
        'community_id: "1"\nupdated_at: x\nmission_hash: h\n'
        "template_version: v2-encyclo-1\nprovider: fake\n---\n"
        "# Subject\n\nLead paragraph stays.\n\n"
        "## Details\n\nDetail body stays.\n\n"
        "## See also\n\n"
        "- [[wiki/topics/gone1.md|Gone 1]]\n"
        "- [[wiki/topics/gone2.md|Gone 2]]\n",
        encoding="utf-8")
    result = writer.reconcile_see_also()
    text = page.read_text(encoding="utf-8")
    assert result == {"links_pruned": 2, "sections_removed": 1}
    assert "## See also" not in text                # header gone
    assert "Lead paragraph stays." in text          # rest of body intact
    assert "## Details" in text and "Detail body stays." in text


def test_prune_dry_run_and_apply(tmp_path):
    vault = make_vault(tmp_path)
    # bare DB -> select_pages returns [] (no protected relpaths from selection)
    db = FakeGraphDB(vault / ".legion" / "graph.sqlite")
    writer = WikiWriter(vault, db, FakeChain(GOOD_BODY))
    topics = vault / "wiki" / "topics"
    topics.mkdir(parents=True)
    (topics / "kept.md").write_text(_generated_page("Kept", "topic:kept"),
                                    encoding="utf-8")     # protected via state
    (topics / "orphan.md").write_text(_generated_page("Orphan", "topic:orphan"),
                                      encoding="utf-8")   # not in state/selection
    (topics / "bake.md").write_text(                      # bakeoff marker under topics/
        "---\ngenerated_by: vexpedia-bakeoff\n---\nx\n", encoding="utf-8")
    state = {"topic:kept": {"relpath": "topics/kept.md", "sources": {},
                            "mission_hash": "h", "provider": "fake",
                            "updated_at": "x"}}
    (vault / ".legion" / "wiki-state.json").write_text(json.dumps(state),
                                                       encoding="utf-8")
    dry = writer.prune(apply=False)
    assert dry["candidates"] == ["topics/orphan.md"]      # only the orphan
    assert dry["deleted"] == 0
    assert (topics / "orphan.md").exists()                # dry-run deletes nothing
    applied = writer.prune(apply=True)
    assert applied["candidates"] == ["topics/orphan.md"]
    assert applied["deleted"] == 1
    assert not (topics / "orphan.md").exists()
    assert (topics / "kept.md").exists()                  # state-protected kept
    assert (topics / "bake.md").exists()                  # bakeoff marker never a candidate


def test_prune_ignores_blocklist_protection(tmp_path):
    vault = make_vault(tmp_path)
    db = FakeGraphDB(vault / ".legion" / "graph.sqlite")
    writer = WikiWriter(vault, db, FakeChain(GOOD_BODY))
    entities = vault / "wiki" / "entities"
    entities.mkdir(parents=True)
    (entities / "blocked.md").write_text(
        _generated_page("Blocked", "entity:blocked"), encoding="utf-8")
    (vault / ".wikiignore").write_text("# pages\nentities/blocked.md\n",
                                       encoding="utf-8")
    result = writer.prune(apply=False)
    assert "entities/blocked.md" in result["candidates"]   # blocklist does not protect
