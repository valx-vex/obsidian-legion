"""Nightly report writer (R5 §9) — lives OUTSIDE the vault.

~/.vex/logs/legion/YYYY-MM-DD.md, one section per vault appended within a day.
REPORT_DIR is a module global so tests monkeypatch it to tmp (never touch the
real ~/.vex). when is injectable for deterministic filenames. Stdlib only.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

REPORT_DIR = Path.home() / ".vex" / "logs" / "legion"


def _render_graph(graph_report: dict) -> list[str]:
    if graph_report.get("error"):
        return [f"- graph: FAILED — {graph_report['error']}"]
    if "skipped" in graph_report:
        return [f"- graph: skipped ({graph_report['skipped']})"]
    keys = ["notes_seen", "changed", "absent_marked", "purged", "embedded",
            "semantic_edges", "communities", "duration_s"]
    parts = [f"{key}={graph_report.get(key)}" for key in keys
             if key in graph_report]
    qdrant = graph_report.get("qdrant_ok")
    if qdrant is not None:
        parts.append(f"qdrant_ok={qdrant}")
    return ["- graph: " + ", ".join(parts)]


def _render_wiki(wiki_report) -> list[str]:
    if wiki_report is None:
        return ["- wiki: not run"]
    if "skipped" in wiki_report:
        return [f"- wiki: skipped — {wiki_report['skipped']}"]
    parts = [
        f"pages written={wiki_report.get('pages_written', 0)}",
        f"skipped={wiki_report.get('pages_skipped', 0)}",
        f"deferred={wiki_report.get('pages_deferred', 0)}",
        f"failed={wiki_report.get('pages_failed', 0)}",
        f"noop={wiki_report.get('noop', False)}",
    ]
    if "pages_by_provider" in wiki_report:
        parts.append(f"pages_by_provider={wiki_report['pages_by_provider']}")
    if "skipped_incoherent" in wiki_report:
        parts.append(f"incoherent={len(wiki_report['skipped_incoherent'])}")
    if "selection_truncated" in wiki_report:
        parts.append(f"truncated={wiki_report['selection_truncated']}")
    if "stale_pages" in wiki_report:
        parts.append(f"stale={wiki_report['stale_pages']}")
    if "see_also_pruned" in wiki_report:
        parts.append(f"see_also_pruned={wiki_report['see_also_pruned']}")
    return [
        "- wiki: " + ", ".join(parts),
        f"- providers: {wiki_report.get('provider_fates', {})}",
    ]


def write_report(vault_name: str, graph_report: dict, wiki_report,
                 when: "datetime | None" = None) -> Path:
    when = when or datetime.now()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{when:%Y-%m-%d}.md"

    lines = [f"## vault: {vault_name} — {when:%H:%M:%S}", ""]
    lines += _render_graph(graph_report)
    lines += _render_wiki(wiki_report)
    section = "\n".join(lines) + "\n"

    if path.exists():
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n" + section)
    else:
        header = f"# Legion nightly — {when:%Y-%m-%d}\n\n"
        path.write_text(header + section, encoding="utf-8")
    return path
