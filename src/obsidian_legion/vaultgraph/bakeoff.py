"""VEXPEDIA bake-off harness (spec §7).

Generates the SAME sample pages with several single-provider HTTP chains
(no fallback) so Valentin can browse them in Obsidian and elect a winner.
Writes only under wiki/_bakeoff/<model-slug>/ with a distinct, non-superstring
marker; never touches wiki-state.json or index.md. Takes the shared
.legion/.lock non-blocking so it cannot read the graph mid-rebuild. Stdlib
only at import; httpx is imported lazily inside ProviderChain._invoke.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import datetime
from pathlib import Path

from .missions import (
    MISSION_TEMPLATE_VERSION, _slug, build_mission_prompt, select_pages,
)
from .providers import ProviderChain
from .sanitize import extract_title, sanitize_output, yaml_quote
from .wiki_writer import WikiWriter, _atomic_write

BAKEOFF_MARKER = "generated_by: vexpedia-bakeoff"

_CITE_RE = re.compile(r"\[\[([^\]|#]+)")


def run_bakeoff(vault_root, db, models: list[str], sample_ids: list[str] | None = None,
                http_client=None, url: str | None = None) -> dict:
    import fcntl

    vault_root = Path(vault_root)
    legion = vault_root / ".legion"
    legion.mkdir(parents=True, exist_ok=True)
    lock_fh = open(legion / ".lock", "w")
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_fh.close()
        return {"skipped": "already_running"}
    try:
        return _run_bakeoff_locked(vault_root, db, models, sample_ids,
                                   http_client, url)
    finally:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        lock_fh.close()


def _run_bakeoff_locked(vault_root, db, models, sample_ids, http_client, url):
    url_base = url or os.environ.get("LEGION_OLLAMA_URL", "http://localhost:11434")
    specs = select_pages(db)
    if sample_ids:
        wanted = set(sample_ids)
        sample = [s for s in specs if s.page_id in wanted]
    else:
        topics = [s for s in specs if s.kind == "topic"][:4]
        entities = [s for s in specs if s.kind == "entity"][:2]
        sample = topics + entities

    validator = WikiWriter(vault_root, db, ProviderChain([]))
    bakeoff_dir = vault_root / "wiki" / "_bakeoff"
    rows: list[dict] = []
    for model in models:
        entry = {"name": model, "kind": "http", "url": url_base,
                 "model": model, "timeout_s": 600}
        chain = ProviderChain([entry], http_client=http_client)
        model_dir = bakeoff_dir / _slug(model)
        for spec in sample:
            prompt = build_mission_prompt(spec, vault_root, None)
            started = time.monotonic()
            result = chain.run_mission(prompt)
            latency = time.monotonic() - started
            row = {"model": model, "page_id": spec.page_id,
                   "relpath": spec.wiki_relpath, "words": 0, "cites": 0,
                   "valid": False, "latency_s": latency, "error": ""}
            if not result.ok:
                row["error"] = result.error
            else:
                body = sanitize_output(result.text)
                page_text = _compose_bakeoff(spec, body, model)
                article = _article_body(page_text)
                row["words"] = len(article.split())
                row["cites"] = len(set(_CITE_RE.findall(article)))
                row["valid"] = validator.validate_page(
                    page_text, kind=spec.kind,
                    n_sources=len(spec.source_relpaths),
                    candidates_provided=bool(spec.related_candidates))
                _atomic_write(model_dir / Path(spec.wiki_relpath).name, page_text)
            rows.append(row)

    report_path = bakeoff_dir / "REPORT.md"
    _atomic_write(report_path, _render_report(rows))
    return {"rows": rows, "report": str(report_path),
            "models": list(models), "sample": [s.page_id for s in sample]}


def _compose_bakeoff(spec, body: str, provider: str) -> str:
    """Bake-off-local compose: BAKEOFF_MARKER + the same other frontmatter keys.

    Deliberately NOT WikiWriter._compose (that stamps the real legion-wiki
    marker). provider is the model name.
    """
    title, _ = extract_title(body)
    if title is None:
        title = spec.title
        body = f"# {spec.title}\n\n" + body
    community_id = spec.key if spec.kind == "topic" else ""
    mission_hash = hashlib.sha256(
        "\n".join(spec.source_relpaths).encode("utf-8")).hexdigest()[:16]
    lines = [
        "---",
        BAKEOFF_MARKER,
        f"title: {yaml_quote(title)}",
        f"page_id: {yaml_quote(spec.page_id)}",
        "sources:",
    ]
    lines += [f"  - {relpath}" for relpath in spec.source_relpaths]
    lines += [
        f'community_id: "{community_id}"',
        f"updated_at: {datetime.now().astimezone().isoformat()}",
        f"mission_hash: {mission_hash}",
        f"template_version: {MISSION_TEMPLATE_VERSION}",
        f"provider: {provider}",
        "---",
        "",
    ]
    return "\n".join(lines) + body + "\n"


def _article_body(page_text: str) -> str:
    if page_text.lstrip().startswith("---"):
        parts = page_text.split("---")
        if len(parts) >= 3:
            return "---".join(parts[2:])
    return page_text


def _render_report(rows: list[dict]) -> str:
    lines = ["# VEXPEDIA bake-off", "",
             "| Model | Page | Words | Cites | Valid | Latency (s) | Error |",
             "|---|---|---|---|---|---|---|"]
    for row in rows:
        error = row["error"].replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {row['model']} | {row['page_id']} | {row['words']} | "
            f"{row['cites']} | {'yes' if row['valid'] else 'no'} | "
            f"{row['latency_s']:.2f} | {error} |")
    return "\n".join(lines) + "\n"


def clean_bakeoff(vault_root) -> dict:
    bakeoff_dir = Path(vault_root) / "wiki" / "_bakeoff"
    removed = 0
    if not bakeoff_dir.exists():
        return {"files_removed": 0}
    for path in sorted(bakeoff_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "REPORT.md":
            path.unlink()
            removed += 1
        elif BAKEOFF_MARKER in path.read_text(encoding="utf-8", errors="ignore"):
            path.unlink()
            removed += 1
    for path in sorted(bakeoff_dir.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if bakeoff_dir.exists() and not any(bakeoff_dir.iterdir()):
        bakeoff_dir.rmdir()
    return {"files_removed": removed}
