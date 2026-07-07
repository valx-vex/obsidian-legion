from __future__ import annotations

from pathlib import Path

from obsidian_legion.vaultgraph.parser import (
    LinkResolver,
    ParsedNote,
    RawLink,
    canonical_key,
    parse_note,
)


def _write(vault: Path, rel: str, content: str) -> Path:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return Path(rel)


def test_parse_wikilink_variants(tmp_path: Path) -> None:
    rel = _write(tmp_path, "n.md",
                 "# Heading One\n\n"
                 "See [[Alpha]], [[Beta|the beta]] and [[Gamma#Section]].\n"
                 "Also [[folder/Delta]].\n")
    note = parse_note(tmp_path, rel)
    triples = {(l.target, l.alias, l.heading) for l in note.links}
    assert ("Alpha", None, None) in triples
    assert ("Beta", "the beta", None) in triples
    assert ("Gamma", None, "Section") in triples
    assert ("folder/Delta", None, None) in triples


def test_code_blocks_stripped_before_extraction(tmp_path: Path) -> None:
    fence = "`" * 3  # assembled at runtime; keeps a literal fence out of this file
    content = (
        "---\n"
        "title: Real Title\n"
        "tags: [fromfm]\n"
        "---\n"
        "# Body Heading\n\n"
        "Real [[RealLink]] and #realtag here.\n\n"
        + fence + "python\n"
        "# not a heading\n"
        'fake = "[[NotALink]]"\n'
        "tag #fakeinsidefence\n"
        + fence + "\n\n"
        "Inline `[[AlsoNotALink]]` and `#notag` stay hidden.\n"
    )
    note = parse_note(tmp_path, _write(tmp_path, "c.md", content))
    targets = {l.target for l in note.links}
    assert "RealLink" in targets
    assert "NotALink" not in targets
    assert "AlsoNotALink" not in targets
    assert "realtag" in note.tags
    assert "fromfm" in note.tags
    assert "fakeinsidefence" not in note.tags
    assert "notag" not in note.tags
    assert note.title == "Real Title"
    # body keeps the ORIGINAL code text (for FTS + embedding input)
    assert "NotALink" in note.body


def test_frontmatter_malformed_is_lenient(tmp_path: Path) -> None:
    content = (
        "---\n"
        "title: Broken\n"
        "tags: [a, b\n"
        "foo: : bad\n"
        "---\n"
        "# Fallback Heading\n\n"
        "Body text with [[Link]].\n"
    )
    note = parse_note(tmp_path, _write(tmp_path, "m.md", content))
    assert note.frontmatter == {}                 # malformed YAML → skipped
    assert note.title == "Fallback Heading"        # falls back to first heading
    assert "Link" in {l.target for l in note.links}
    assert "Body text" in note.body


def test_title_precedence(tmp_path: Path) -> None:
    n1 = parse_note(tmp_path, _write(tmp_path, "one.md",
                                     "---\ntitle: FM Title\n---\n# H1\nbody"))
    assert n1.title == "FM Title"
    n2 = parse_note(tmp_path, _write(tmp_path, "two.md", "# Heading Wins\n\nbody"))
    assert n2.title == "Heading Wins"
    n3 = parse_note(tmp_path, _write(tmp_path, "some-note.md", "just body, no heading"))
    assert n3.title == "some-note"


def test_tags_inline_and_frontmatter_deduped(tmp_path: Path) -> None:
    content = (
        "---\n"
        "tags:\n"
        "  - alpha\n"
        "  - beta\n"
        "---\n"
        "Body with #beta and #gamma tags. Nested #area/sub too.\n"
    )
    note = parse_note(tmp_path, _write(tmp_path, "t.md", content))
    assert "alpha" in note.tags
    assert "beta" in note.tags
    assert "gamma" in note.tags
    assert "area/sub" in note.tags
    assert note.tags.count("beta") == 1
    assert all(not t.startswith("#") for t in note.tags)


def test_canonical_key() -> None:
    assert canonical_key("Valentin") == "valentin"
    assert canonical_key("  Valentin  ") == "valentin"
    assert canonical_key("Sacred   Flame") == "sacred flame"
    assert canonical_key("VALENTIN") == canonical_key("valentin")
    assert canonical_key("Murphy\tSleeps") == "murphy sleeps"


def test_resolver_exact_path() -> None:
    r = LinkResolver(["04_Legion/Notes/Alpha.md", "Beta.md"])
    assert r.resolve("04_Legion/Notes/Alpha") == "04_Legion/Notes/Alpha.md"
    assert r.resolve("04_Legion/Notes/Alpha.md") == "04_Legion/Notes/Alpha.md"
    assert r.resolve("nonexistent/Path") is None


def test_resolver_basename_case_insensitive() -> None:
    r = LinkResolver(["folder/Alpha.md"])
    assert r.resolve("alpha") == "folder/Alpha.md"
    assert r.resolve("ALPHA") == "folder/Alpha.md"
    assert r.resolve("Alpha.md") == "folder/Alpha.md"


def test_resolver_tie_break_depth_then_lex() -> None:
    r = LinkResolver(["z/Alpha.md", "a/b/Alpha.md", "m/Alpha.md"])
    # depth 1: z/Alpha.md and m/Alpha.md; a/b/Alpha.md is depth 2 (loses);
    # lexicographic between the two depth-1 winners → m/Alpha.md
    assert r.resolve("Alpha") == "m/Alpha.md"


def test_resolver_phantom_returns_none() -> None:
    r = LinkResolver(["Alpha.md"])
    assert r.resolve("Ghost") is None
