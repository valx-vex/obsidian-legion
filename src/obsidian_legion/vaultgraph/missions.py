"""Page selection + OpenWiki-method mission prompts (R5 §5.1/§5.2).

select_pages is deterministic and DB-driven: it reads the graph SQLite
read-only (via db.db_path) and derives the bounded VEXPEDIA page set —
topics from communities (>= min size, ranked by size * mean PageRank),
entities from notes above the p95 PageRank percentile OR phantoms with
degree >= phantom_min_degree (excluded-basename phantoms were already dropped
at graph-build time, §2.1). Stdlib only (sqlite3 + math); percentile is a
nearest-rank index computation, no numpy.

build_mission_prompt embeds the OpenWiki rules verbatim, switches to surgical
update mode when an existing page is supplied, and trims grounding excerpts to
excerpt_budget chars total. WikiWriter owns the machine frontmatter; the
prompt asks the model for the page body.
"""
from __future__ import annotations

import math
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

MISSION_TEMPLATE_VERSION = "r5-openwiki-1"
_GROUNDING_CAP = 12                       # max source notes cited per page

MISSION_RULES = """\
You are compiling ONE page for VEXPEDIA, a generated wiki over a personal
Obsidian vault. Follow these OpenWiki rules EXACTLY:

1. NEVER invent. Every claim must be grounded in the source excerpts below.
   If the sources do not support a statement, do not write it.
2. Cite sources inline as [[wikilinks]] to the note paths given. Every page
   MUST contain at least one [[wikilink]].
3. No thin pages. If the sources only justify two sentences, write two solid
   grounded sentences — never pad, never speculate to hit a length.
4. One canonical home per concept: this page is the single home for its
   subject; link out to related pages rather than duplicating them.
5. Surgical updates only: when an existing page is shown, change the minimum
   needed to reflect new/changed sources; preserve wording that is still
   correct. Do not rewrite wholesale.
6. Output ONLY the page BODY in Markdown (headings + prose + [[wikilinks]]).
   Do NOT emit YAML frontmatter — the compiler adds generated_by, sources,
   community_id, updated_at, and mission_hash itself.
"""


@dataclass
class PageSpec:
    kind: str            # 'topic' | 'entity'
    key: str             # community_id as str, or node id
    wiki_relpath: str    # 'topics/<slug>.md' | 'entities/<slug>.md'
    title: str
    source_relpaths: list[str]


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).strip().lower()).strip("-")
    return slug or "page"


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return float("inf")
    rank = max(1, math.ceil(percentile / 100.0 * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def select_pages(db, max_pages: int = 300, min_community_size: int = 5,
                 pagerank_percentile: float = 95.0,
                 phantom_min_degree: int = 5) -> list[PageSpec]:
    db_path = getattr(db, "db_path", None)
    if db_path is None:
        raise ValueError("select_pages requires db.db_path (GraphDB sqlite path)")

    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        nodes = {row["id"]: row for row in conn.execute(
            "SELECT id, kind, title, canonical_key, path, community_id, pagerank, "
            "absent_since FROM nodes")}
        inbound: dict[str, list[str]] = defaultdict(list)
        degree: dict[str, int] = defaultdict(int)
        for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind='wikilink'"):
            inbound[dst].append(src)
            degree[dst] += 1
        community_names: dict[int, str] = {}
        try:
            for cid, name in conn.execute("SELECT community_id, name FROM communities"):
                community_names[cid] = name
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()

    def note_path(node_id: str):
        row = nodes.get(node_id)
        if row and row["kind"] == "note" and row["path"] and row["absent_since"] is None:
            return row["path"]
        return None

    def pr(row) -> float:
        return row["pagerank"] if row["pagerank"] is not None else 0.0

    active_notes = [r for r in nodes.values()
                    if r["kind"] == "note" and r["absent_since"] is None]

    # --- topic pages: communities by size * mean pagerank -------------------
    members: dict[int, list] = defaultdict(list)
    for row in active_notes:
        if row["community_id"] is not None:
            members[row["community_id"]].append(row)

    topic_ranked = []
    topic_member_ids: set[str] = set()   # notes owned by a qualifying topic page
    for cid, mem in members.items():
        if len(mem) < min_community_size:
            continue
        topic_member_ids.update(m["id"] for m in mem)
        mean_pr = sum(pr(m) for m in mem) / len(mem)
        score = len(mem) * mean_pr
        top = sorted(mem, key=lambda m: (-pr(m), m["path"]))[:_GROUNDING_CAP]
        name = community_names.get(cid) or (top[0]["title"] if top else f"community-{cid}")
        spec = PageSpec(kind="topic", key=str(cid),
                        wiki_relpath=f"topics/{_slug(f'{cid}-{name}')}.md",
                        title=name,
                        source_relpaths=[m["path"] for m in top if m["path"]])
        topic_ranked.append((score, cid, spec))
    topic_ranked.sort(key=lambda t: (-t[0], t[1]))
    topics = [t[2] for t in topic_ranked]

    # --- entity pages: p95 notes + high-degree phantoms ---------------------
    threshold = _percentile(sorted(pr(r) for r in active_notes), pagerank_percentile)
    entity_ranked = []
    for row in active_notes:
        if pr(row) < threshold or row["id"] in topic_member_ids:
            continue          # canonical home is the topic page (OpenWiki rule 4)
        srcs = [row["path"]] + [note_path(s) for s in inbound.get(row["id"], [])]
        srcs = [s for s in dict.fromkeys(srcs) if s][:_GROUNDING_CAP]
        title = row["title"] or row["path"]
        entity_ranked.append((pr(row), row["id"], PageSpec(
            kind="entity", key=row["id"],
            wiki_relpath=f"entities/{_slug(title)}.md", title=title,
            source_relpaths=srcs)))

    for node_id, row in nodes.items():
        if row["kind"] != "phantom" or degree.get(node_id, 0) < phantom_min_degree:
            continue
        srcs = [note_path(s) for s in inbound.get(node_id, [])]
        srcs = [s for s in dict.fromkeys(srcs) if s][:_GROUNDING_CAP]
        if not srcs:
            continue
        title = row["title"] or row["canonical_key"] or node_id
        entity_ranked.append((float(degree[node_id]), node_id, PageSpec(
            kind="entity", key=node_id,
            wiki_relpath=f"entities/{_slug(title)}.md", title=title,
            source_relpaths=srcs)))
    entity_ranked.sort(key=lambda t: (-t[0], str(t[1])))
    entities = [t[2] for t in entity_ranked]

    selected: list[PageSpec] = []
    seen: set[str] = set()
    for spec in topics + entities:
        if spec.wiki_relpath in seen:
            continue
        seen.add(spec.wiki_relpath)
        selected.append(spec)
    return selected[:max_pages]


def build_mission_prompt(spec: PageSpec, vault_root: Path,
                         existing_page: str | None,
                         excerpt_budget: int = 24000) -> str:
    vault_root = Path(vault_root)
    grounding_parts: list[str] = []
    total = 0
    for relpath in spec.source_relpaths:
        if total >= excerpt_budget:
            break
        source = vault_root / relpath
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        chunk = text[: max(0, excerpt_budget - total)]
        total += len(chunk)
        grounding_parts.append(f"### SOURCE [[{relpath}]]\n{chunk}")
    grounding = "\n\n".join(grounding_parts) or "(no readable source notes)"

    sections = [
        MISSION_RULES,
        f"## PAGE\nkind: {spec.kind}\ntitle: {spec.title}\n",
    ]
    if existing_page is not None:
        sections.append(
            "## SURGICAL UPDATE — current page (edit minimally to match new sources):\n"
            + existing_page)
    sections.append("## GROUNDING SOURCES (cite these as [[path]]):\n" + grounding)
    sections.append(
        f"## TASK\nWrite the Markdown BODY for the page titled '{spec.title}'. "
        "Ground every claim in the sources above and include at least one "
        "[[wikilink]]. Output the body only.")
    return "\n\n".join(sections)
