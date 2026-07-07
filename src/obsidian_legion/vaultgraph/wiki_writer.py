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

_FRONTMATTER_KEYS = ("generated_by", "sources", "community_id",
                     "updated_at", "mission_hash")
_GENERATED_MARKER = "generated_by: legion-wiki"


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
                  "provider_fates": {}}

        specs = [s for s in select_pages(self.db)
                 if s.wiki_relpath not in self._blocklist()]
        state = self._load_state()

        dropped = 0
        for page in list(state.keys()):
            if not (self.wiki_root / page).exists():
                del state[page]
                dropped += 1

        work = []
        for spec in specs:
            current = self._current_sources(spec)
            entry = state.get(spec.wiki_relpath)
            page_file = self.wiki_root / spec.wiki_relpath
            needs = (entry is None or not page_file.exists()
                     or entry.get("sources") != current
                     or entry.get("mission_hash") != self._mission_hash(current))
            if needs:
                work.append((spec, current))

        if not work and dropped == 0:
            report["noop"] = True
            report["provider_fates"] = {
                name: ("ready" if ok else "unavailable")
                for name, ok in self.chain.preflight().items()}
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
            return report

        started = time.monotonic()
        processed = 0
        for spec, current in to_write:
            # Wall-clock budget: defer the remaining pages if the night is spent.
            if max_wall_s is not None and time.monotonic() - started >= max_wall_s:
                report["wall_clock_stop"] = True
                break
            outcome = self._generate(spec, current, fates)
            if outcome == "written":
                report["pages_written"] += 1
                state[spec.wiki_relpath] = {
                    "sources": current, "mission_hash": self._mission_hash(current)}
            elif outcome == "failed":
                report["pages_failed"] += 1
            else:
                report["pages_skipped"] += 1
            processed += 1

        if report["wall_clock_stop"]:
            report["pages_deferred"] += len(to_write) - processed

        self._save_state(state)
        self.write_index(specs)
        report["provider_fates"] = fates
        return report

    def reset(self, regenerate: bool = False) -> dict:
        removed = 0
        for sub in ("topics", "entities"):
            directory = self.wiki_root / sub
            if directory.exists():
                for page in directory.glob("*.md"):
                    if _GENERATED_MARKER in page.read_text(encoding="utf-8", errors="ignore"):
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

    def write_index(self, specs: list[PageSpec]) -> Path:
        topics = sorted((s for s in specs if s.kind == "topic"),
                        key=lambda s: s.wiki_relpath)
        entities = sorted((s for s in specs if s.kind == "entity"),
                          key=lambda s: s.wiki_relpath)
        lines = ["# VEXPEDIA",
                 "",
                 "_Auto-generated index (no LLM). Regenerated when the page set changes._",
                 ""]
        for label, group in (("Topics", topics), ("Entities", entities)):
            lines.append(f"## {label}")
            lines.append("")
            lines.append("| Page | Sources |")
            lines.append("|---|---|")
            for spec in group:
                lines.append(f"| [[wiki/{spec.wiki_relpath}\\|{spec.title}]] "
                             f"| {len(spec.source_relpaths)} |")
            lines.append("")
        index = self.wiki_root / "index.md"
        _atomic_write(index, "\n".join(lines) + "\n")
        return index

    def validate_page(self, text: str) -> bool:
        if not text or not text.strip():
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
        return "[[" in body and "]]" in body

    # -- internals ----------------------------------------------------------
    def _generate(self, spec: PageSpec, current: dict, fates: dict) -> str:
        page_file = self.wiki_root / spec.wiki_relpath
        existing = page_file.read_text(encoding="utf-8") if page_file.exists() else None
        prompt = build_mission_prompt(spec, self.vault_root, existing)
        for _attempt in (1, 2):
            result = self.chain.run_mission(prompt)
            for name in getattr(self.chain, "dead_providers", set()):
                fates[name] = "quota_exhausted"
            if not getattr(result, "ok", False):
                return "skipped"
            if result.provider:
                fates[result.provider] = "used"
            page_text = self._compose(spec, current, result.text)
            if self.validate_page(page_text):
                _atomic_write(page_file, page_text)
                return "written"
        return "failed"

    def _compose(self, spec: PageSpec, current: dict, body: str) -> str:
        body = self._strip_frontmatter(body).strip()
        community_id = spec.key if spec.kind == "topic" else ""
        lines = ["---", _GENERATED_MARKER, "sources:"]
        lines += [f"  - {relpath}" for relpath in spec.source_relpaths]
        lines += [
            f'community_id: "{community_id}"',
            f"updated_at: {datetime.now().astimezone().isoformat()}",
            f"mission_hash: {self._mission_hash(current)}",
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
