import json

from obsidian_legion.vaultgraph.sanitize import (
    extract_title, sanitize_output, yaml_quote,
)


# -- sanitize_output: ANSI / control / zero-width -------------------------

def test_sanitize_strips_ansi_csi_interleaved_in_word():
    # Real v1 corruption shape: cursor-move + erase-line escapes shredded
    # citations mid-token. We strip the escapes; we do not replay the cursor.
    raw = "daily/2026-6\x1b[2D\x1b[K-10"
    out = sanitize_output(raw)
    assert "\x1b" not in out
    assert out == "daily/2026-6-10"


def test_sanitize_strips_ansi_inside_wikilink():
    raw = "See [[daily/2026-6\x1b[2D\x1b[K-10]] today"
    out = sanitize_output(raw)
    assert "\x1b" not in out
    assert out == "See [[daily/2026-6-10]] today"


def test_sanitize_strips_osc_sequence():
    raw = "before\x1b]0;window title\x07after"
    out = sanitize_output(raw)
    assert "\x1b" not in out
    assert out == "beforeafter"


def test_sanitize_strips_bare_escape():
    raw = "a\x1bXb"
    out = sanitize_output(raw)
    assert "\x1b" not in out
    assert out == "ab"


def test_sanitize_c0_controls_stripped_but_tab_and_newline_kept():
    raw = "line1\nline2\ttab\x00\x07\x1fend\rnext"
    out = sanitize_output(raw)
    # \n and \t survive; \x00 \x07 \x1f \r are removed
    assert out == "line1\nline2\ttabendnext"


def test_sanitize_removes_zero_width_chars():
    raw = "a​b‌‍c﻿d"
    assert sanitize_output(raw) == "abcd"


# -- sanitize_output: reasoning blocks ------------------------------------

def test_sanitize_removes_closed_think_block():
    raw = "before<think>secret chain of thought</think>after"
    assert sanitize_output(raw) == "beforeafter"


def test_sanitize_removes_think_block_multiline_and_case_insensitive():
    raw = "# Title\n<THINK>\nmulti\nline\nreasoning\n</Think>\nbody"
    out = sanitize_output(raw)
    assert "think" not in out.lower()
    assert "reasoning" not in out
    assert out.startswith("# Title")
    assert "body" in out


def test_sanitize_removes_unclosed_think_to_eof():
    raw = "keep this<think>unclosed reasoning\nmore\nlines"
    assert sanitize_output(raw) == "keep this"


def test_sanitize_removes_gpt_oss_span_with_done_marker():
    raw = ("Thinking...\n"
           "The user wants a page.\n"
           "Let me plan it.\n"
           "...done thinking.\n"
           "\n"
           "# Docker Phoenix\n"
           "\n"
           "Body with [[a]].")
    out = sanitize_output(raw)
    assert "Thinking..." not in out
    assert "done thinking" not in out
    assert out.startswith("# Docker Phoenix")
    assert "[[a]]" in out


def test_sanitize_removes_gpt_oss_span_no_marker_but_heading_follows():
    raw = ("Thinking...\n"
           "reasoning one\n"
           "reasoning two\n"
           "\n"
           "# Real Title\n"
           "\n"
           "Body.")
    out = sanitize_output(raw)
    assert "Thinking..." not in out
    assert "reasoning one" not in out
    assert out.startswith("# Real Title")


# -- sanitize_output: preamble before the authored H1 ---------------------

def test_sanitize_drops_preamble_before_h1():
    raw = "Okay, let me think about this.\n\n# Real Title\n\nBody text here."
    assert sanitize_output(raw) == "# Real Title\n\nBody text here."


def test_sanitize_does_not_drop_when_no_heading():
    raw = "Just some prose.\nNo heading anywhere."
    assert sanitize_output(raw) == "Just some prose.\nNo heading anywhere."


# -- extract_title --------------------------------------------------------

def test_extract_title_happy_path():
    body = "# Docker Phoenix\n\nA container platform."
    title, returned = extract_title(body)
    assert title == "Docker Phoenix"
    assert returned == body            # body returned unchanged


def test_extract_title_cleans_forbidden_chars():
    body = "# Title with [[link]] and | pipe and `code`\n\nbody"
    title, _ = extract_title(body)
    assert title == "Title with link and pipe and code"
    for bad in ("[[", "]]", "|", "`"):
        assert bad not in title


def test_extract_title_skips_leading_blank_lines():
    body = "\n\n# Late Title\nbody"
    title, returned = extract_title(body)
    assert title == "Late Title"
    assert returned == body


def test_extract_title_no_h1_returns_none_and_body():
    body = "Just a paragraph.\nSecond line, no heading."
    title, returned = extract_title(body)
    assert title is None
    assert returned == body


# -- yaml_quote -----------------------------------------------------------

def test_yaml_quote_escapes_and_round_trips():
    # A double-quoted YAML scalar uses the same escaping as a JSON string, so
    # json.loads(yaml_quote(v)) must round-trip back to v — this catches a
    # wrong replace() order (quotes-before-backslashes would double-escape).
    for value in ('simple', 'Docker: Phoenix', 'say "hi"', 'back\\slash',
                  'edge \\ and " together'):
        quoted = yaml_quote(value)
        assert quoted.startswith('"') and quoted.endswith('"')
        assert json.loads(quoted) == value

    # explicit shapes
    assert yaml_quote('Docker: Phoenix') == '"Docker: Phoenix"'   # colon passes through
    assert yaml_quote('say "hi"') == '"say \\"hi\\""'
    assert yaml_quote('back\\slash') == '"back\\\\slash"'
