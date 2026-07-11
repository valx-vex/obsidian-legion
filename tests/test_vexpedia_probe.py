# tests/test_vexpedia_probe.py
import importlib.util
from pathlib import Path


def _load_probe():
    path = Path(__file__).resolve().parents[1] / "scripts" / "vexpedia_probe.py"
    spec = importlib.util.spec_from_file_location("vexpedia_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


probe = _load_probe()

_MARKER = "generated_by: legion-wiki"


def _page_text(sources, body):
    fm = ["---", _MARKER, 'title: "T"', 'page_id: "entity:x"', "sources:"]
    fm += [f"  - {s}" for s in sources]
    fm += ['community_id: ""', "updated_at: 2026-07-10T00:00:00",
           "mission_hash: abcd1234", "template_version: v2-encyclo-1",
           "provider: ollama", "---", "", body, ""]
    return "\n".join(fm)


def _write_page(wiki, relpath, sources=(), body="# T\n\nBody."):
    page = wiki / relpath
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(_page_text(sources, body), encoding="utf-8")
    return page


def _write_index(wiki, relpaths):
    wiki.mkdir(parents=True, exist_ok=True)
    lines = ["# VEXPEDIA", "", "## Topics", "", "| Page | Sources |", "|---|---|"]
    for rp in relpaths:
        lines.append(f"| [[wiki/{rp}\\|Title]] | 1 |")
    (wiki / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_corruption_clean_passes(tmp_path):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "a.md").write_text(
        "# A\n\nClean encyclopedic prose. See [[wiki/topics/b.md]].",
        encoding="utf-8")
    ok, messages = probe.probe_corruption(tmp_path)
    assert ok is True
    assert any("clean" in m.lower() for m in messages)


def test_corruption_esc_byte_fails(tmp_path):
    (tmp_path / "a.md").write_text("# A\n\nText\x1b[2Kmore", encoding="utf-8")
    ok, messages = probe.probe_corruption(tmp_path)
    assert ok is False
    assert any("ESC" in m for m in messages)


def test_corruption_think_block_fails(tmp_path):
    (tmp_path / "a.md").write_text(
        "# A\n\n<think>secret reasoning</think>\nBody", encoding="utf-8")
    ok, messages = probe.probe_corruption(tmp_path)
    assert ok is False
    assert any("think" in m.lower() for m in messages)


def test_corruption_thinking_line_fails(tmp_path):
    (tmp_path / "a.md").write_text(
        "Thinking...\nchain of thought\n...done thinking.\n# A\n\nBody",
        encoding="utf-8")
    ok, messages = probe.probe_corruption(tmp_path)
    assert ok is False
    assert any("Thinking" in m for m in messages)


def test_privacy_fails_on_private_source(tmp_path):
    vault = tmp_path / "vault"
    _write_page(vault / "wiki", "topics/a.md",
                sources=[".murphy_private/garden.md", "notes/pub.md"],
                body="# A\n\nBody.")
    ok, messages = probe.probe_privacy(vault)
    assert ok is False
    assert any(".murphy_private" in m for m in messages)


def test_privacy_fails_on_private_basename_stem(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".murphy_private").mkdir(parents=True)
    (vault / ".murphy_private" / "secret-garden.md").write_text(
        "private", encoding="utf-8")
    _write_page(vault / "wiki", "topics/a.md", sources=["notes/pub.md"],
                body="# A\n\nDiscusses secret-garden at length.")
    ok, messages = probe.probe_privacy(vault)
    assert ok is False
    assert any("secret-garden" in m for m in messages)


def test_privacy_passes_traceable_public_mention(tmp_path):
    vault = tmp_path / "vault"
    (vault / "notes").mkdir(parents=True)
    (vault / "notes" / "essay.md").write_text(
        "An essay that names the .murphy_private folder in prose.",
        encoding="utf-8")
    _write_page(vault / "wiki", "topics/a.md", sources=["notes/essay.md"],
                body="# A\n\nThe source discusses the .murphy_private folder.")
    ok, messages = probe.probe_privacy(vault)
    assert ok is True


def test_privacy_fails_untraceable_private_literal(tmp_path):
    vault = tmp_path / "vault"
    (vault / "notes").mkdir(parents=True)
    (vault / "notes" / "clean.md").write_text(
        "A perfectly clean public note.", encoding="utf-8")
    _write_page(vault / "wiki", "topics/a.md", sources=["notes/clean.md"],
                body="# A\n\nLeaks the .murphy_private literal with no source.")
    ok, messages = probe.probe_privacy(vault)
    assert ok is False
    assert any("murphy_private" in m for m in messages)


def test_index_exact_match_passes(tmp_path):
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    _write_page(wiki, "topics/a.md", body="# A\n\nBody.")
    _write_page(wiki, "entities/b.md", body="# B\n\nBody.")
    _write_index(wiki, ["topics/a.md", "entities/b.md"])
    ok, messages = probe.probe_index(vault)
    assert ok is True
    assert any("exact match" in m for m in messages)


def test_index_extra_row_fails(tmp_path):
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    _write_page(wiki, "topics/a.md", body="# A\n\nBody.")
    _write_index(wiki, ["topics/a.md", "topics/ghost.md"])  # ghost not on disk
    ok, messages = probe.probe_index(vault)
    assert ok is False
    assert any("ghost.md" in m for m in messages)


def test_index_extra_disk_page_fails(tmp_path):
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    _write_page(wiki, "topics/a.md", body="# A\n\nBody.")
    _write_page(wiki, "topics/b.md", body="# B\n\nBody.")
    _write_index(wiki, ["topics/a.md"])                     # b.md not listed
    ok, messages = probe.probe_index(vault)
    assert ok is False
    assert any("topics/b.md" in m for m in messages)


def test_deadlinks_resolving_passes(tmp_path):
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    _write_page(wiki, "topics/a.md", body="# A\n\nSee [[wiki/topics/b.md]].")
    _write_page(wiki, "topics/b.md", body="# B\n\nBody.")
    ok, messages = probe.probe_deadlinks(vault)
    assert ok is True


def test_deadlinks_missing_target_fails(tmp_path):
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    _write_page(wiki, "topics/a.md", body="# A\n\nSee [[wiki/topics/gone.md]].")
    ok, messages = probe.probe_deadlinks(vault)
    assert ok is False
    assert any("gone.md" in m for m in messages)


def test_deadlinks_ignores_non_wiki_links(tmp_path):
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    _write_page(wiki, "topics/a.md",
                body="# A\n\nSee [[notes/raw.md]] and [[SomeNote]].")
    ok, messages = probe.probe_deadlinks(vault)
    assert ok is True


def test_mobile_identical_passes(tmp_path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    for root in (src, dest):
        _write_page(root / "wiki", "topics/a.md", body="# A\n\nBody.")
        _write_page(root / "wiki", "entities/b.md", body="# B\n\nBody.")
    ok, messages = probe.probe_mobile(src, dest)
    assert ok is True
    assert any("match" in m for m in messages)


def test_mobile_dest_missing_file_fails(tmp_path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    _write_page(src / "wiki", "topics/a.md", body="# A\n\nBody.")
    _write_page(src / "wiki", "topics/b.md", body="# B\n\nBody.")
    _write_page(dest / "wiki", "topics/a.md", body="# A\n\nBody.")
    ok, messages = probe.probe_mobile(src, dest)
    assert ok is False
    assert any("topics/b.md" in m for m in messages)


def test_mobile_dest_extra_file_fails(tmp_path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    _write_page(src / "wiki", "topics/a.md", body="# A\n\nBody.")
    _write_page(dest / "wiki", "topics/a.md", body="# A\n\nBody.")
    _write_page(dest / "wiki", "topics/extra.md", body="# X\n\nBody.")
    ok, messages = probe.probe_mobile(src, dest)
    assert ok is False
    assert any("topics/extra.md" in m for m in messages)


# --- Fix 1: anchored intra-wiki links must strip the #fragment ---


def test_deadlinks_anchored_link_resolving_passes(tmp_path):
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    _write_page(wiki, "topics/a.md",
                body="# A\n\nSee [[wiki/topics/b.md#Some-Heading|B]].")
    _write_page(wiki, "topics/b.md", body="# B\n\nBody.")
    ok, messages = probe.probe_deadlinks(vault)
    assert ok is True


def test_deadlinks_anchored_link_missing_target_fails(tmp_path):
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    _write_page(wiki, "topics/a.md",
                body="# A\n\nSee [[wiki/topics/gone.md#Some-Heading|G]].")
    ok, messages = probe.probe_deadlinks(vault)
    assert ok is False
    assert any("gone.md" in m for m in messages)


def test_index_anchored_link_matches(tmp_path):
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    _write_page(wiki, "topics/b.md", body="# B\n\nBody.")
    _write_index(wiki, ["topics/b.md#Some-Heading"])
    ok, messages = probe.probe_index(vault)
    assert ok is True
    assert any("exact match" in m for m in messages)


# --- Fix 2: empty/missing dirs must FAIL, not vacuously pass ---


def test_corruption_missing_dir_fails(tmp_path):
    ok, messages = probe.probe_corruption(tmp_path / "does-not-exist")
    assert ok is False
    assert any("no .md files found" in m for m in messages)


def test_corruption_empty_dir_fails(tmp_path):
    (tmp_path / "empty").mkdir()
    ok, messages = probe.probe_corruption(tmp_path / "empty")
    assert ok is False
    assert any("no .md files found" in m for m in messages)


def test_mobile_empty_source_fails(tmp_path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    _write_page(dest / "wiki", "topics/a.md", body="# A\n\nBody.")
    ok, messages = probe.probe_mobile(src, dest)
    assert ok is False
    assert any("no pages" in m for m in messages)


# --- Fix 3: private stem match is word-bounded and only for len >= 4 ---


def test_privacy_short_stem_word_does_not_fire(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".murphy_private").mkdir(parents=True)
    (vault / ".murphy_private" / "a.md").write_text("private", encoding="utf-8")
    _write_page(vault / "wiki", "topics/clean.md", sources=["docs/pub.md"],
                body="# Clean\n\nThis is a perfectly clean public page.")
    ok, messages = probe.probe_privacy(vault)
    assert ok is True


def test_privacy_whole_word_stem_fires(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".murphy_private").mkdir(parents=True)
    (vault / ".murphy_private" / "notes.md").write_text(
        "private", encoding="utf-8")
    _write_page(vault / "wiki", "topics/a.md", sources=["docs/pub.md"],
                body="# A\n\nThese are my notes for today.")
    ok, messages = probe.probe_privacy(vault)
    assert ok is False
    assert any("notes" in m for m in messages)


def test_privacy_stem_boundary_ignores_superstrings(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".murphy_private").mkdir(parents=True)
    (vault / ".murphy_private" / "notes.md").write_text(
        "private", encoding="utf-8")
    _write_page(vault / "wiki", "topics/a.md", sources=["docs/pub.md"],
                body="# A\n\nSee the footnotes and the field-notes section.")
    ok, messages = probe.probe_privacy(vault)
    assert ok is True


def test_privacy_basename_literal_still_fires(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".murphy_private").mkdir(parents=True)
    (vault / ".murphy_private" / "a.md").write_text("private", encoding="utf-8")
    _write_page(vault / "wiki", "topics/x.md", sources=["docs/pub.md"],
                body="# X\n\nReference to a.md appears literally here.")
    ok, messages = probe.probe_privacy(vault)
    assert ok is False
    assert any("a.md" in m for m in messages)


def test_main_exit_codes(tmp_path):
    (tmp_path / "clean.md").write_text("# A\n\nClean prose.", encoding="utf-8")
    assert probe.main(["corruption", str(tmp_path)]) == 0     # pass -> 0
    (tmp_path / "bad.md").write_text("# B\n\n<think>x</think>", encoding="utf-8")
    assert probe.main(["corruption", str(tmp_path)]) == 1     # fail -> 1
