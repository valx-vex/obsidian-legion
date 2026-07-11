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
