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
from dataclasses import dataclass, field
from pathlib import Path

MISSION_TEMPLATE_VERSION = "v2-encyclo-1"
_GROUNDING_CAP = 12                       # max source notes cited per page

MISSION_RULES = """\
You are compiling ONE page for VEXPEDIA, an encyclopedic wiki generated over a
personal Obsidian vault. Follow these rules EXACTLY:

1. NEVER invent. Every claim must be grounded in the source excerpts below.
   If the sources do not support a statement, do not write it.
2. Write in English, in a neutral encyclopedic voice. Keep technical terms,
   code, and quotations verbatim as they appear in the sources.
3. Structure the page as: a single `# <real descriptive title you author>`
   heading, then a lead paragraph of 2-3 sentences that synthesizes the
   subject, then 2 to 4 `##` thematic sections, then a `## See also` section.
   The `# ` title line must NOT contain `[[`, `]]`, `|`, or backticks.
4. Synthesize across the sources. When three or more sources are provided,
   cite at least three distinct sources as [[wikilinks]] and weave them
   together — do not merely summarize a single note.
5. Target 300-600 words. Never pad to reach a length, but a topic page backed
   by five or more sources that runs under ~120 words is a failure.
6. End with `## See also` containing 2 to 5 entries chosen ONLY from the
   RELATED PAGES candidate list provided below, copying each chosen entry
   EXACTLY as it appears in that list (entries look like
   `[[wiki/<relpath>|<title>]]`). If no candidate list is provided, omit the
   `## See also` section entirely.
7. Sources that are fiction or roleplay (SCP entries, stories) are described AS
   fiction (e.g. "In the SCP-styled fiction ..."); never state their
   in-universe claims as fact.
8. Output the page BODY only — no YAML frontmatter, no reasoning, no
   meta-commentary. The compiler adds all machine frontmatter itself.
"""


@dataclass
class PageSpec:
    kind: str                    # 'topic' | 'entity'
    key: str                     # community_id as str, or node id
    wiki_relpath: str            # 'topics/<slug>.md' | 'entities/<slug>.md'
    title: str                   # anchor/entity title (deterministic fallback)
    source_relpaths: list[str]
    page_id: str = ""            # 'topic:<anchor_relpath>' | 'entity:<path|key>'
    related_candidates: list[tuple[str, str]] = field(default_factory=list)
    # related_candidates: [(wiki_relpath, title)], max _RELATED_CAP entries


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).strip().lower()).strip("-")
    return slug or "page"


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return float("inf")
    rank = max(1, math.ceil(percentile / 100.0 * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def _fair_share(lengths: list[int], budget: int) -> list[int]:
    """Max-min water-filling of `budget` chars over source lengths (R5 v2 §5.3).

    Hand every still-competing source an equal `share`; any source shorter than
    its share is satisfied at its true length and drops out, donating its slack
    back to the pool for the next pass. When a pass satisfies nobody, the long
    sources left split the remainder equally and the residue (< n_remaining)
    goes to the FIRST remaining source (list order == PageRank order). Sum of
    the result is always <= budget.
    """
    n = len(lengths)
    alloc = [0] * n
    if n == 0:
        return alloc
    unsatisfied = list(range(n))
    remaining = budget
    while unsatisfied:
        share = remaining // len(unsatisfied)
        satisfied = [i for i in unsatisfied if lengths[i] <= share]
        if not satisfied:
            break
        done = set(satisfied)
        for i in satisfied:
            alloc[i] = lengths[i]
            remaining -= lengths[i]
        unsatisfied = [i for i in unsatisfied if i not in done]
    if unsatisfied:
        share = remaining // len(unsatisfied)
        for i in unsatisfied:
            alloc[i] = share
        residue = remaining - share * len(unsatisfied)   # < len(unsatisfied)
        alloc[unsatisfied[0]] += residue                 # first == highest PageRank
    return alloc


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
                         excerpt_budget: int = 60000) -> str:
    vault_root = Path(vault_root)
    # Read every source first (dropping unreadable ones), then fair-share the
    # budget across what we actually have so a long first note cannot starve
    # the rest (R5 v2 §5.3). Each excerpt is truncated to its own allocation.
    readable: list[tuple[str, str]] = []
    for relpath in spec.source_relpaths:
        try:
            text = (vault_root / relpath).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        readable.append((relpath, text))
    allocations = _fair_share([len(t) for _, t in readable], excerpt_budget)
    grounding_parts = [f"### SOURCE [[{relpath}]]\n{text[:alloc]}"
                       for (relpath, text), alloc in zip(readable, allocations)]
    grounding = "\n\n".join(grounding_parts) or "(no readable source notes)"

    sections = [
        MISSION_RULES,
        f"## PAGE\nkind: {spec.kind}\ntitle: {spec.title}\n",
    ]
    if existing_page is not None:
        sections.append(
            "## SURGICAL UPDATE — current page (edit minimally to match new sources):\n"
            + existing_page)
    if spec.related_candidates:
        # Render with the vault-absolute 'wiki/' prefix — the model copies these
        # lines verbatim into '## See also', and validate_page/reconcile/index/
        # probes all key off the '[[wiki/...' form (pre-flight scan fix).
        candidate_lines = "\n".join(
            f"- [[wiki/{relpath}|{title}]]" for relpath, title in spec.related_candidates)
        sections.append(
            "## RELATED PAGES (candidates for See also):\n" + candidate_lines)
    sections.append("## GROUNDING SOURCES (cite these as [[path]]):\n" + grounding)
    sections.append(
        f"## TASK\nWrite the Markdown BODY for the VEXPEDIA page about "
        f"'{spec.title}'. Author a real, descriptive title as the H1. Ground "
        "every claim in the sources above, synthesize across them, and choose "
        "any '## See also' entries only from the RELATED PAGES list. Output the "
        "body only.")
    return "\n\n".join(sections)
