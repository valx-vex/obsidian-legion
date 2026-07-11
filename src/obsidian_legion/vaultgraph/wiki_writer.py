"""VEXPEDIA wiki writer — surgical, budgeted, resumable (R5 §5.3).

Owns the machine frontmatter (generated_by / sources / community_id /
updated_at / mission_hash); the mission model supplies only the body. Change
detection compares per-page source sha256 + a mission_hash (template version
+ source shas) against <vault>/.legion/wiki-state.json. No-op nights write
nothing (not even index). Out-of-band-deleted pages drop their state entry and
regenerate. Permanent deletion is the .wikiignore '# pages' blocklist, never a
raw file delete (mobile sync would resurrect it). Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .missions import (
    MISSION_TEMPLATE_VERSION, PageSpec, build_mission_prompt, select_pages,
)
from .sanitize import extract_title, sanitize_output, yaml_quote

_FRONTMATTER_KEYS = ("generated_by", "title", "page_id", "sources",
                     "community_id", "updated_at", "mission_hash",
                     "template_version", "provider")
_GENERATED_MARKER = "generated_by: legion-wiki"
_GENERATED_LINE_RE = re.compile(r"^generated_by: legion-wiki\s*$", re.MULTILINE)


def _is_generated(text: str) -> bool:
    """True iff `text` carries the anchored legion-wiki generated marker.

    Anchored to a whole frontmatter line so bake-off markers
    ('generated_by: vexpedia-bakeoff') and superstrings
    ('generated_by: legion-wiki-bakeoff') never match.
    """
    return bool(_GENERATED_LINE_RE.search(text))


_TITLE_LINE_RE = re.compile(r'^title:\s*"(.*)"\s*$', re.MULTILINE)
_SOURCES_LINE_RE = re.compile(r"^sources:\s*$")
_SEE_ALSO_HEADER_RE = re.compile(r"^##\s+See also\s*$", re.IGNORECASE)
_WIKI_LINK_RE = re.compile(r"\[\[(wiki/[^\]|#]+)")


def _frontmatter_block(text: str) -> str:
    """Return the YAML frontmatter (between the first two '---'), or ''."""
    if not text.lstrip().startswith("---"):
        return ""
    parts = text.split("---")
    return parts[1] if len(parts) >= 3 else ""


def _unescape_yaml(value: str) -> str:
    """Reverse yaml_quote's escaping of a double-quoted scalar body."""
    out: list[str] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value):
            out.append(value[i + 1])
            i += 2
        else:
            out.append(char)
            i += 1
    return "".join(out)


def _parse_title(text: str) -> str | None:
    match = _TITLE_LINE_RE.search(_frontmatter_block(text))
    if not match:
        return None
    return _unescape_yaml(match.group(1))


def _count_sources(text: str) -> int:
    count = 0
    in_sources = False
    for line in _frontmatter_block(text).splitlines():
        if _SOURCES_LINE_RE.match(line):
            in_sources = True
            continue
        if in_sources:
            if line.startswith("  - "):
                count += 1
            elif line and not line[0].isspace():
                break
    return count


def _reconcile_see_also_text(text: str, vault_root: Path):
    """Prune dead [[wiki/...]] bullets from the first '## See also' section.

    Returns (new_text, links_pruned, sections_removed). Only the See-also
    section is touched; dead links elsewhere in the body are left alone.
    """
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if _SEE_ALSO_HEADER_RE.match(line):
            start = i
            break
    if start is None:
        return text, 0, 0
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    header, section, tail = lines[:start], lines[start:end], lines[end:]
    pruned = 0
    kept = [section[0]]                       # the '## See also' header line
    for line in section[1:]:
        match = _WIKI_LINK_RE.search(line)
        if match and not (vault_root / match.group(1)).exists():
            pruned += 1
            continue
        kept.append(line)
    if any("[[" in ln for ln in kept[1:]):
        return "\n".join(header + kept + tail), pruned, 0
    return "\n".join(header + tail), pruned, 1


class WikiWriter:
    def __init__(self, vault_root, db, chain, state_path=None) -> None:
        self.vault_root = Path(vault_root)
        self.db = db
        self.chain = chain
        self.wiki_root = self.vault_root / "wiki"
        self.state_path = Path(state_path) if state_path else \
            self.vault_root / ".legion" / "wiki-state.json"

    # -- public API ---------------------------------------------------------
    def update(self, budget: int = 25, bootstrap: bool = False,
               bootstrap_cap: int = 150, max_wall_s: int | None = 1800) -> dict:
        # Same lock as the graph writer (spec §4.6): the wiki phase must not run
        # concurrently with an in-progress graph rebuild. Each phase takes the
        # lock itself; nightly never holds it around both.
        import fcntl

        legion = self.vault_root / ".legion"
        legion.mkdir(parents=True, exist_ok=True)
        lock_fh = open(legion / ".lock", "w")
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock_fh.close()
            return {"skipped": "already_running", "noop": True}

        try:
            return self._update_locked(budget, bootstrap, bootstrap_cap, max_wall_s)
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            lock_fh.close()

    def _update_locked(self, budget: int, bootstrap: bool, bootstrap_cap: int,
                       max_wall_s: int | None) -> dict:
        report = {"pages_written": 0, "pages_skipped": 0, "pages_deferred": 0,
                  "pages_failed": 0, "noop": False, "wall_clock_stop": False,
                  "provider_fates": {}, "pages_by_provider": {},
                  "skipped_incoherent": [], "selection_truncated": 0,
                  "stale_pages": 0, "see_also_pruned": 0}

        sel_report: dict = {}
        blocklist = self._blocklist()
        specs = [s for s in select_pages(self.db, selection_report=sel_report)
                 if s.wiki_relpath not in blocklist]
        report["skipped_incoherent"] = sel_report.get("skipped_incoherent", [])
        report["selection_truncated"] = sel_report.get("selection_truncated", 0)
        state = self._load_state()

        # Reconcile: state is keyed by page_id; an entry whose recorded relpath
        # file is gone (out-of-band delete) is dropped and regenerated.
        dropped = 0
        for page_id in list(state.keys()):
            relpath = state[page_id].get("relpath")
            if not relpath or not (self.wiki_root / relpath).exists():
                del state[page_id]
                dropped += 1

        work = []
        for spec in specs:
            current = self._current_sources(spec)
            entry = state.get(spec.page_id)
            page_file = self.wiki_root / spec.wiki_relpath
            needs = (entry is None or not page_file.exists()
                     or entry.get("relpath") != spec.wiki_relpath
                     or entry.get("sources") != current
                     or entry.get("mission_hash") != self._mission_hash(current))
            if needs:
                work.append((spec, current))

        if not work and dropped == 0:
            report["noop"] = True
            report["provider_fates"] = {
                name: ("ready" if ok else "unavailable")
                for name, ok in self.chain.preflight().items()}
            report["stale_pages"] = self._count_stale(state)
            return report

        cap = bootstrap_cap if bootstrap else budget
        to_write = work[:cap]
        report["pages_deferred"] = max(0, len(work) - len(to_write))

        fates = {name: ("ready" if ok else "unavailable")
                 for name, ok in self.chain.preflight().items()}
        if not any(state_ == "ready" for state_ in fates.values()):
            report["pages_skipped"] = len(to_write)
            report["provider_fates"] = fates
            self._save_state(state)                 # persist reconciliation
            report["stale_pages"] = self._count_stale(state)
            return report

        started = time.monotonic()
        processed = 0
        for spec, current in to_write:
            # Wall-clock budget: defer the remaining pages if the night is spent.
            if max_wall_s is not None and time.monotonic() - started >= max_wall_s:
                report["wall_clock_stop"] = True
                break
            old_entry = state.get(spec.page_id)
            old_relpath = old_entry.get("relpath") if old_entry else None
            outcome, provider = self._generate(spec, current, fates)
            if outcome == "written":
                report["pages_written"] += 1
                report["pages_by_provider"][provider] = \
                    report["pages_by_provider"].get(provider, 0) + 1
                state[spec.page_id] = {
                    "relpath": spec.wiki_relpath,
                    "sources": current,
                    "mission_hash": self._mission_hash(current),
                    "provider": provider,
                    "updated_at": datetime.now().astimezone().isoformat()}
                # Relpath migration: the anchor slug changed, so the old
                # generated file is renamed away (deleted after the new write).
                if old_relpath and old_relpath != spec.wiki_relpath:
                    old_file = self.wiki_root / old_relpath
                    if old_file.exists() and _is_generated(
                            old_file.read_text(encoding="utf-8", errors="ignore")):
                        old_file.unlink()
            elif outcome == "failed":
                report["pages_failed"] += 1
            else:
                report["pages_skipped"] += 1
            processed += 1

        if report["wall_clock_stop"]:
            report["pages_deferred"] += len(to_write) - processed

        self._save_state(state)
        report["see_also_pruned"] = self.reconcile_see_also()["links_pruned"]
        self.write_index()
        report["provider_fates"] = fates
        report["stale_pages"] = self._count_stale(state)
        return report

    def reset(self, regenerate: bool = False) -> dict:
        removed = 0
        for sub in ("topics", "entities"):
            directory = self.wiki_root / sub
            if directory.exists():
                for page in directory.glob("*.md"):
                    if _is_generated(page.read_text(encoding="utf-8", errors="ignore")):
                        page.unlink()
                        removed += 1
        index = self.wiki_root / "index.md"
        if index.exists():
            index.unlink()
            removed += 1
        state_removed = False
        if regenerate and self.state_path.exists():
            self.state_path.unlink()
            state_removed = True
        return {"pages_removed": removed, "state_removed": state_removed}

    def write_index(self) -> Path:
        lines = ["# VEXPEDIA",
                 "",
                 "_Auto-generated index (no LLM). Regenerated when the page set changes._",
                 ""]
        for label, sub in (("Topics", "topics"), ("Entities", "entities")):
            lines.append(f"## {label}")
            lines.append("")
            lines.append("| Page | Sources |")
            lines.append("|---|---|")
            for relpath, title, n_sources in self._index_entries(sub):
                lines.append(f"| [[wiki/{relpath}\\|{title}]] | {n_sources} |")
            lines.append("")
        index = self.wiki_root / "index.md"
        _atomic_write(index, "\n".join(lines) + "\n")
        return index

    def _index_entries(self, sub: str) -> list[tuple[str, str, int]]:
        directory = self.wiki_root / sub
        if not directory.exists():
            return []
        entries: list[tuple[str, str, int]] = []
        for page in sorted(directory.glob("*.md")):
            text = page.read_text(encoding="utf-8", errors="ignore")
            if not _is_generated(text):
                continue
            relpath = f"{sub}/{page.name}"
            title = _parse_title(text) or page.stem
            entries.append((relpath, title, _count_sources(text)))
        return entries

    def reconcile_see_also(self) -> dict:
        links_pruned = 0
        sections_removed = 0
        for sub in ("topics", "entities"):
            directory = self.wiki_root / sub
            if not directory.exists():
                continue
            for page in sorted(directory.glob("*.md")):
                text = page.read_text(encoding="utf-8", errors="ignore")
                if not _is_generated(text):
                    continue
                new_text, pruned, removed = _reconcile_see_also_text(
                    text, self.vault_root)
                if new_text != text:
                    _atomic_write(page, new_text)
                links_pruned += pruned
                sections_removed += removed
        return {"links_pruned": links_pruned, "sections_removed": sections_removed}

    def validate_page(self, text: str, *, kind: str = "", n_sources: int = 0,
                      candidates_provided: bool = False) -> bool:
        if not text or not text.strip():
            return False
        if "\x1b" in text:                       # residual ANSI escape
            return False
        if not text.lstrip().startswith("---"):
            return False
        parts = text.split("---")
        if len(parts) < 3:
            return False
        frontmatter, body = parts[1], "---".join(parts[2:])
        for key in _FRONTMATTER_KEYS:
            if not re.search(rf"^{key}\s*:", frontmatter, re.MULTILINE):
                return False
        if not body.strip():
            return False
        if "[[" not in body or "]]" not in body:
            return False
        if "<think>" in text.lower():            # residual reasoning block
            return False
        for line in body.splitlines():
            if line.startswith("Thinking...") or "...done thinking." in line:
                return False
        first = next(ln for ln in body.splitlines() if ln.strip())
        if not re.match(r"^# \S", first):        # authored H1
            return False
        if "[[" in first or "|" in first or "`" in first:
            return False
        if candidates_provided:
            idx = body.find("## See also")
            if idx < 0 or "[[wiki/" not in body[idx:]:
                return False
        words = len(body.split())
        if kind == "topic" and n_sources >= 5 and words < 120:
            return False
        if kind == "entity" and words < 60:
            return False
        return True

    # -- internals ----------------------------------------------------------
    def _generate(self, spec: PageSpec, current: dict,
                  fates: dict) -> tuple[str, str]:
        page_file = self.wiki_root / spec.wiki_relpath
        existing = page_file.read_text(encoding="utf-8") if page_file.exists() else None
        prompt = build_mission_prompt(spec, self.vault_root, existing)
        for _attempt in (1, 2):
            result = self.chain.run_mission(prompt)
            for name in getattr(self.chain, "dead_providers", set()):
                fates[name] = "quota_exhausted"
            if not getattr(result, "ok", False):
                return "skipped", ""
            if result.provider:
                fates[result.provider] = "used"
            body = sanitize_output(result.text)
            page_text = self._compose(spec, current, body, result.provider)
            if self.validate_page(
                    page_text, kind=spec.kind,
                    n_sources=len(spec.source_relpaths),
                    candidates_provided=bool(spec.related_candidates)):
                _atomic_write(page_file, page_text)
                return "written", result.provider
        return "failed", ""

    def _compose(self, spec: PageSpec, current: dict, body: str,
                 provider: str) -> str:
        title, _ = extract_title(body)
        if title is None:
            title = spec.title
            body = f"# {spec.title}\n\n" + body
        community_id = spec.key if spec.kind == "topic" else ""
        lines = ["---", _GENERATED_MARKER,
                 f"title: {yaml_quote(title)}",
                 f"page_id: {yaml_quote(spec.page_id)}",
                 "sources:"]
        lines += [f"  - {relpath}" for relpath in spec.source_relpaths]
        lines += [
            f'community_id: "{community_id}"',
            f"updated_at: {datetime.now().astimezone().isoformat()}",
            f"mission_hash: {self._mission_hash(current)}",
            f"template_version: {MISSION_TEMPLATE_VERSION}",
            f"provider: {provider}",
            "---",
            "",
        ]
        return "\n".join(lines) + body + "\n"

    @staticmethod
    def _strip_frontmatter(text: str) -> str:
        if text.lstrip().startswith("---"):
            parts = text.split("---")
            if len(parts) >= 3:
                return "---".join(parts[2:])
        return text

    def _current_sources(self, spec: PageSpec) -> dict:
        sources = {}
        for relpath in spec.source_relpaths:
            path = self.vault_root / relpath
            try:
                sources[relpath] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
        return sources

    def _mission_hash(self, current: dict) -> str:
        payload = f"{MISSION_TEMPLATE_VERSION}\n" + "\n".join(
            f"{relpath}:{current[relpath]}" for relpath in sorted(current))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _count_stale(self, state: dict) -> int:
        """Generated-marker pages on disk not referenced by any state relpath."""
        referenced = {entry.get("relpath") for entry in state.values()}
        stale = 0
        for sub in ("topics", "entities"):
            directory = self.wiki_root / sub
            if not directory.exists():
                continue
            for page in directory.glob("*.md"):
                if f"{sub}/{page.name}" in referenced:
                    continue
                if _is_generated(page.read_text(encoding="utf-8", errors="ignore")):
                    stale += 1
        return stale

    def _blocklist(self) -> set[str]:
        ignore = self.vault_root / ".wikiignore"
        if not ignore.exists():
            return set()
        blocked: set[str] = set()
        in_pages = False
        for raw in ignore.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.lower() == "# pages":
                in_pages = True
                continue
            if not in_pages or not line or line.startswith("#"):
                continue
            blocked.add(line)
        return blocked

    def _load_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        tmp.replace(self.state_path)


def _atomic_write(path: Path, content: str) -> None:
    """Write via a same-dir temp file + os.replace (mirrors wiki_store).

    A crash mid-write never leaves a half-written page or index behind; the
    replace only touches (and re-mtimes) the target when a real write happens.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=path.parent
    ) as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)
