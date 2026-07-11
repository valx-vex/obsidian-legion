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


def _wiki_v2(**kw):
    base = _wiki()
    base.update({
        "pages_by_provider": {"ollama": 3, "gemini": 1},
        "skipped_incoherent": ["topics/junk-a.md", "topics/junk-b.md"],
        "selection_truncated": 7,
        "stale_pages": 4,
        "see_also_pruned": 5,
    })
    base.update(kw)
    return base


def _wiki_line(text: str) -> str:
    return next(line for line in text.splitlines() if line.startswith("- wiki:"))


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


def test_graph_skipped_renders_reason(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path / "legion")
    path = report.write_report("exegesis", {"skipped": "no changes since last run"},
                               None, when=datetime(2026, 7, 8))
    text = path.read_text().lower()
    assert "graph: skipped" in text and "no changes since last run" in text


def test_when_defaults_to_now(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path / "legion")
    path = report.write_report("exegesis", _graph(), _wiki())
    assert path.suffix == ".md" and len(path.stem) == 10   # YYYY-MM-DD


def test_wiki_v2_keys_render_on_wiki_line(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path / "legion")
    path = report.write_report("exegesis", _graph(), _wiki_v2(),
                               when=datetime(2026, 7, 10, 5, 15))
    line = _wiki_line(path.read_text())
    assert "pages written=4" in line                       # legacy fields kept
    assert "pages_by_provider={'ollama': 3, 'gemini': 1}" in line
    assert "incoherent=2" in line                          # len(skipped_incoherent)
    assert "truncated=7" in line
    assert "stale=4" in line
    assert "see_also_pruned=5" in line


def test_wiki_v1_shape_omits_v2_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path / "legion")
    path = report.write_report("exegesis", _graph(), _wiki(),
                               when=datetime(2026, 7, 10, 5, 15))
    line = _wiki_line(path.read_text())
    for absent in ("pages_by_provider", "incoherent", "truncated", "stale",
                   "see_also_pruned"):
        assert absent not in line
    # Legacy wiki line is byte-for-byte unchanged.
    assert line == ("- wiki: pages written=4, skipped=0, deferred=2, "
                    "failed=0, noop=False")
