# tests/test_vg_bakeoff.py
import fcntl
import sqlite3

import httpx

from obsidian_legion.vaultgraph.bakeoff import (
    BAKEOFF_MARKER, clean_bakeoff, run_bakeoff,
)


class FakeGraphDB:
    """test_vg_missions-style stand-in: owns a sqlite file with the locked
    nodes/edges/communities schema, exposed via db_path."""

    def __init__(self, db_path):
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

    def add_wikilink(self, src, dst):
        self._exec("INSERT INTO edges (src, dst, kind, weight) VALUES (?,?,?,1.0)",
                   (src, dst, "wikilink"))

    def _exec(self, sql, params):
        conn = sqlite3.connect(self.db_path)
        conn.execute(sql, params)
        conn.commit()
        conn.close()


def _build_db(legion_dir):
    # two coherent communities (every member has an intra-community neighbor)
    db = FakeGraphDB(legion_dir / "graph.sqlite")
    for c in (1, 2):
        node_ids = [f"c{c}n{i}" for i in range(5)]
        for i, nid in enumerate(node_ids):
            db.add_note(nid, f"c{c}/{i}.md", pagerank=0.5, community_id=c,
                        title=f"Note {c}-{i}")
        for nid in node_ids[1:]:
            db.add_wikilink(nid, node_ids[0])
        db.add_wikilink(node_ids[0], node_ids[1])
    return db


def _good_body():
    prose = ("This subject synthesizes several grounded notes into one coherent "
             "encyclopedic overview drawing on multiple distinct sources. ") * 10
    return ("# A Real Descriptive Title\n\n" + prose +
            "\n\nThe topic connects to [[notes/c1/0.md]] and related material.\n\n"
            "## See also\n\n- [[wiki/topics/other.md|Other]]\n")


def _short_body():
    return "# Short\n\nToo few [[notes/x]] words to pass the floor."


def _mock_client(body_fn):
    def handler(request):
        return httpx.Response(200, json={"message": {"content": body_fn()}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def _vault(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".legion").mkdir(parents=True)
    return vault


def test_bakeoff_writes_pages_with_marker(tmp_path):
    vault = _vault(tmp_path)
    db = _build_db(vault / ".legion")
    result = run_bakeoff(vault, db, ["minimax-m3:cloud", "glm-5:cloud"],
                         http_client=_mock_client(_good_body))
    for model in ("minimax-m3-cloud", "glm-5-cloud"):
        pages = list((vault / "wiki" / "_bakeoff" / model).glob("*.md"))
        assert pages, f"no pages for {model}"
        for page in pages:
            assert BAKEOFF_MARKER in page.read_text(encoding="utf-8")
    assert all(row["valid"] for row in result["rows"])


def test_bakeoff_never_writes_state_or_index(tmp_path):
    vault = _vault(tmp_path)
    db = _build_db(vault / ".legion")
    run_bakeoff(vault, db, ["glm-5:cloud"], http_client=_mock_client(_good_body))
    assert not (vault / ".legion" / "wiki-state.json").exists()
    assert not (vault / "wiki" / "index.md").exists()


def test_bakeoff_skipped_when_lock_held(tmp_path):
    vault = _vault(tmp_path)
    db = _build_db(vault / ".legion")
    lock = open(vault / ".legion" / ".lock", "w")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = run_bakeoff(vault, db, ["glm-5:cloud"],
                             http_client=_mock_client(_good_body))
        assert result == {"skipped": "already_running"}
        assert not (vault / "wiki" / "_bakeoff").exists()
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def test_bakeoff_validation_failure_recorded_as_row(tmp_path):
    vault = _vault(tmp_path)
    db = _build_db(vault / ".legion")
    result = run_bakeoff(vault, db, ["glm-5:cloud"],
                         http_client=_mock_client(_short_body))
    assert result["rows"]
    assert all(row["valid"] is False for row in result["rows"])   # too short
    assert all(row["error"] == "" for row in result["rows"])       # http ok; validation failed


def test_bakeoff_report_has_model_page_rows(tmp_path):
    vault = _vault(tmp_path)
    db = _build_db(vault / ".legion")
    run_bakeoff(vault, db, ["minimax-m3:cloud", "glm-5:cloud"],
                http_client=_mock_client(_good_body))
    report = (vault / "wiki" / "_bakeoff" / "REPORT.md").read_text(encoding="utf-8")
    assert "minimax-m3:cloud" in report and "glm-5:cloud" in report
    assert "topic:c1/0.md" in report and "topic:c2/0.md" in report


def test_bakeoff_sample_ids_filter_honored(tmp_path):
    vault = _vault(tmp_path)
    db = _build_db(vault / ".legion")
    result = run_bakeoff(vault, db, ["glm-5:cloud"],
                         sample_ids=["topic:c1/0.md"],
                         http_client=_mock_client(_good_body))
    assert {row["page_id"] for row in result["rows"]} == {"topic:c1/0.md"}
    written = {p.name for p in (vault / "wiki" / "_bakeoff" / "glm-5-cloud").glob("*.md")}
    assert written == {"note-1-0.md"}      # basename of topics/note-1-0.md


def test_clean_bakeoff_removes_marker_and_report_keeps_foreign(tmp_path):
    vault = tmp_path / "vault"
    bake = vault / "wiki" / "_bakeoff" / "m"
    bake.mkdir(parents=True)
    (bake / "a.md").write_text("---\ngenerated_by: vexpedia-bakeoff\n---\n# A\n",
                               encoding="utf-8")
    (vault / "wiki" / "_bakeoff" / "REPORT.md").write_text("# report\n",
                                                           encoding="utf-8")
    foreign = bake / "keepme.txt"
    foreign.write_text("not a bakeoff file", encoding="utf-8")
    result = clean_bakeoff(vault)
    assert result["files_removed"] == 2
    assert not (bake / "a.md").exists()
    assert not (vault / "wiki" / "_bakeoff" / "REPORT.md").exists()
    assert foreign.exists()


import argparse

from obsidian_legion import cli


def _cli_vault(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".legion").mkdir(parents=True)
    conn = sqlite3.connect(vault / ".legion" / "graph.sqlite")
    conn.executescript(
        "CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, title TEXT, "
        "canonical_key TEXT, path TEXT, mtime REAL, sha256 TEXT, "
        "community_id INTEGER, centrality REAL, pagerank REAL, absent_since REAL);"
        "CREATE TABLE edges (src TEXT, dst TEXT, kind TEXT, weight REAL, annotation TEXT);"
        "CREATE TABLE communities (community_id INTEGER PRIMARY KEY, name TEXT, "
        "size INTEGER, top_members_json TEXT);")
    conn.commit()
    conn.close()
    return vault


def test_cli_wiki_prune_handler_applies(tmp_path):
    vault = _cli_vault(tmp_path)
    topics = vault / "wiki" / "topics"
    topics.mkdir(parents=True)
    (topics / "orphan.md").write_text(
        "---\ngenerated_by: legion-wiki\n"
        'title: "O"\npage_id: "topic:o"\nsources:\n  - x.md\n'
        'community_id: ""\nupdated_at: x\nmission_hash: h\n'
        "template_version: v2-encyclo-1\nprovider: fake\n---\n# O\n\nB [[wiki/x]].\n",
        encoding="utf-8")
    args = argparse.Namespace(vault_root=vault, apply=True)
    rc = cli._handle_wiki_prune(args, cli.CliUI())
    assert rc == 0
    assert not (topics / "orphan.md").exists()      # --apply deleted the orphan


def test_cli_wiki_bakeoff_clean_handler(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    bake = vault / "wiki" / "_bakeoff" / "m"
    bake.mkdir(parents=True)
    (bake / "a.md").write_text("---\ngenerated_by: vexpedia-bakeoff\n---\n# A\n",
                               encoding="utf-8")
    args = argparse.Namespace(vault_root=vault, clean=True,
                              models="glm-5:cloud", sample=None)
    rc = cli._handle_wiki_bakeoff(args, cli.CliUI())
    assert rc == 0
    assert not (bake / "a.md").exists()             # --clean removed it
