from datetime import datetime

from obsidian_legion.vaultgraph import report


def _graph(**kw):
    base = {"vault": "exegesis", "notes_seen": 24000, "changed": 12,
            "absent_marked": 3, "purged": 1, "embedded": 12, "semantic_edges": 96,
            "communities": 210, "duration_s": 74.2, "qdrant_ok": True}
    base.update(kw)
    return base


def _wiki(**kw):
    base = {"pages_written": 4, "pages_skipped": 0, "pages_deferred": 2,
            "pages_failed": 0, "noop": False,
            "provider_fates": {"gemini": "used", "codex": "ready"}}
    base.update(kw)
    return base


def test_writes_dated_file_with_counts(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path / "legion")
    when = datetime(2026, 7, 8, 5, 15)
    path = report.write_report("exegesis", _graph(), _wiki(), when=when)
    assert path.name == "2026-07-08.md"
    text = path.read_text()
    assert "exegesis" in text
    assert "24000" in text and "communities" in text.lower()
    assert "pages written" in text.lower() and "4" in text
    assert "deferred" in text.lower()                     # cap never truncates silently


def test_appends_second_vault_section_same_day(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path / "legion")
    when = datetime(2026, 7, 8, 5, 15)
    report.write_report("exegesis", _graph(vault="exegesis"), _wiki(), when=when)
    path = report.write_report("cathedral-prime", _graph(vault="cathedral-prime"),
                               _wiki(), when=when)
    text = path.read_text()
    assert text.count("# Legion nightly") == 1            # single day header
    assert "exegesis" in text and "cathedral-prime" in text
    assert text.count("## vault:") == 2                    # two vault sections


def test_wiki_none_renders_graph_only(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path / "legion")
    path = report.write_report("exegesis", _graph(), None,
                               when=datetime(2026, 7, 8))
    text = path.read_text().lower()
    assert "wiki" in text and ("not run" in text or "skipped" in text)


def test_wiki_skipped_dict_renders_reason(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path / "legion")
    path = report.write_report("exegesis", _graph(),
                               {"skipped": "all providers down"},
                               when=datetime(2026, 7, 8))
    assert "all providers down" in path.read_text().lower()


def test_graph_error_is_surfaced(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path / "legion")
    path = report.write_report("exegesis", {"error": "qdrant refused"}, None,
                               when=datetime(2026, 7, 8))
    assert "qdrant refused" in path.read_text().lower()


def test_when_defaults_to_now(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path / "legion")
    path = report.write_report("exegesis", _graph(), _wiki())
    assert path.suffix == ".md" and len(path.stem) == 10   # YYYY-MM-DD
