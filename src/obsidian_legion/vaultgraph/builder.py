from __future__ import annotations

import json
import time
from pathlib import Path


class GraphBuilder:
    def __init__(self, vault_root, db_path=None, manifest_path=None,
                 embedder=None, exclusions=None) -> None:
        self.vault_root = Path(vault_root)
        legion = self.vault_root / ".legion"
        self.db_path = Path(db_path) if db_path else legion / "graph.sqlite"
        self.manifest_path = (Path(manifest_path) if manifest_path
                              else legion / "graph-manifest.json")
        self.lock_path = legion / ".lock"
        self.embedder = embedder
        self.exclusions = exclusions

    # ---- manifest ---------------------------------------------------------
    def _load_manifest(self) -> dict:
        if not self.manifest_path.exists():
            return {}
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_manifest(self, manifest: dict) -> None:
        import os
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.manifest_path)

    @staticmethod
    def _sha256(path: Path) -> str:
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _default_embedder(self):
        from .embedder import VaultEmbedder
        return VaultEmbedder()

    # ---- structural graph -------------------------------------------------
    def _structural(self, included, private_stems):
        from .parser import LinkResolver, canonical_key, parse_note

        resolver = LinkResolver(list(included))
        nodes: dict[str, dict] = {}
        edges: set[tuple[str, str, str]] = set()
        fts_rows: list[dict] = []
        parsed: dict[str, object] = {}

        def _node(nid, kind, title, path=None, mtime=None):
            nodes.setdefault(nid, {
                "id": nid, "kind": kind, "title": title,
                "canonical_key": canonical_key(title or nid),
                "path": path, "mtime": mtime, "sha256": None,
                "community_id": None, "centrality": None,
                "pagerank": None, "absent_since": None,
            })

        for rel in included:
            note = parse_note(self.vault_root, Path(rel))
            parsed[rel] = note
            mtime = (self.vault_root / rel).stat().st_mtime
            _node(rel, "note", note.title or Path(rel).stem, path=rel, mtime=mtime)
            fts_rows.append({"id": rel, "title": note.title, "body": note.body})
            folder = Path(rel).parent.as_posix()
            fid = f"folder:{folder}"
            _node(fid, "folder", folder)
            edges.add((rel, fid, "folder"))
            for tag in note.tags:
                tid = f"tag:{tag}"
                _node(tid, "tag", tag)
                edges.add((rel, tid, "tag"))
            for link in note.links:
                target = resolver.resolve(link.target)
                if target is not None:
                    edges.add((rel, target, "wikilink"))
                    continue
                # Normalize to a bare basename-stem before the private check:
                # link targets may carry a ".md" suffix or a path prefix that
                # canonical_key alone would leak past the stem-based blocklist.
                # Parser already splits alias/heading — the defensive splits are
                # free belt-and-braces.
                raw = link.target.split("#")[0].split("|")[0].strip()
                stem = Path(raw).name
                if stem.lower().endswith(".md"):
                    stem = stem[:-3]
                probe = canonical_key(stem)
                ck = canonical_key(link.target)
                if ck in private_stems or probe in private_stems:
                    continue
                pid = f"phantom:{ck}"
                _node(pid, "phantom", link.target)
                edges.add((rel, pid, "wikilink"))

        edge_list = [{"src": s, "dst": d, "kind": k, "weight": 1.0, "annotation": None}
                     for (s, d, k) in sorted(edges)]
        return nodes, edge_list, fts_rows, parsed

    def _tombstone(self, rel, sha, ts):
        from .parser import canonical_key
        stem = Path(rel).stem
        return {"id": rel, "kind": "note", "title": stem,
                "canonical_key": canonical_key(stem), "path": rel, "mtime": None,
                "sha256": sha, "community_id": None, "centrality": None,
                "pagerank": None, "absent_since": ts}

    def _embed_payloads(self, changed, parsed, sha):
        payloads = []
        for rel in changed:
            note = parsed[rel]
            text = "\n".join([note.title, *note.headings, note.body])
            payloads.append({
                "relpath": rel, "title": note.title, "tags": list(note.tags),
                "folder": Path(rel).parent.as_posix(),
                "mtime": (self.vault_root / rel).stat().st_mtime,
                "sha256": sha[rel], "text": text,
            })
        return payloads

    # ---- main -------------------------------------------------------------
    def update(self, full: bool = False, skip_embeddings: bool = False) -> dict:
        import fcntl

        from .analytics import compute_analytics
        from .exclusion import ExclusionEngine
        from .graphdb import GraphDB
        from .parser import canonical_key

        started = time.time()
        legion = self.vault_root / ".legion"
        legion.mkdir(parents=True, exist_ok=True)

        lock_fh = open(self.lock_path, "w")
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock_fh.close()
            return {"skipped": "already_running"}

        try:
            exclusions = self.exclusions or ExclusionEngine(self.vault_root)
            candidates = [Path(p).as_posix() for p in exclusions.iter_notes()]
            manifest = {} if full else self._load_manifest()

            # Reading each note's bytes (for its content hash) is the first place
            # a note's content is touched — before parsing. A note that iter_notes
            # lists but can't be read (e.g. a dangling ``.md`` symlink) must be
            # skipped AND counted: never silent, never fatal to an unattended run.
            # Drop it from the included set so it never reaches parsing, nodes, or
            # the manifest — treated exactly as if excluded. If it was present on a
            # prior run it then falls naturally into the absent/purge path below by
            # its disappearance from ``included_set``.
            sha: dict[str, str] = {}
            included: list[str] = []
            unreadable: list[str] = []
            for rel in candidates:
                try:
                    sha[rel] = self._sha256(self.vault_root / rel)
                except OSError:
                    unreadable.append(rel)
                    continue
                included.append(rel)
            included_set = set(included)

            changed = [rel for rel in included if manifest.get(rel) != sha[rel]]

            private_basenames: set[str] = set()
            private_stems: set[str] = set()
            for path in self.vault_root.rglob("*.md"):
                rel = path.relative_to(self.vault_root)
                if exclusions.is_hard_private(rel):
                    private_basenames.add(rel.name)
                    private_stems.add(canonical_key(rel.stem))

            gone = [rel for rel in manifest if rel not in included_set]
            purge = [rel for rel in gone
                     if exclusions.is_hard_private(rel) or Path(rel).name in private_basenames]
            purge_set = set(purge)
            absent = [rel for rel in gone if rel not in purge_set]

            nodes_map, edges, fts_rows, parsed = self._structural(included, private_stems)
            ts = time.time()
            for rel in absent:
                nodes_map[rel] = self._tombstone(rel, manifest.get(rel), ts)
                fts_rows.append({"id": rel, "title": Path(rel).stem, "body": ""})
            for rel in included:
                nodes_map[rel]["sha256"] = sha[rel]

            qdrant_ok = True
            embedded = 0
            semantic_edges: list[dict] = []
            if skip_embeddings:
                qdrant_ok = False
            else:
                embedder = self.embedder or self._default_embedder()
                try:
                    embedder.ensure_collection()
                    embedded = embedder.upsert_notes(self._embed_payloads(changed, parsed, sha))
                    if absent:
                        embedder.mark_absent(absent, ts)
                    if purge:
                        embedder.delete_points(purge)
                    semantic_edges = embedder.knn_edges()
                except Exception:
                    qdrant_ok = False
                    semantic_edges = []

            valid_ids = set(nodes_map)
            semantic_edges = [{**e, "kind": "semantic"} for e in semantic_edges
                              if e.get("src") in valid_ids and e.get("dst") in valid_ids]
            edges.extend(semantic_edges)

            nodes = list(nodes_map.values())
            analytics = compute_analytics(nodes, edges)
            for node in nodes:
                node["community_id"] = analytics.community_of.get(node["id"])
                node["pagerank"] = analytics.pagerank.get(node["id"])
                node["centrality"] = analytics.centrality.get(node["id"])

            db = GraphDB(self.db_path)
            db.rebuild(nodes, edges, fts_rows)
            db.set_analytics(
                {n["id"]: {"community_id": n["community_id"],
                           "pagerank": n["pagerank"],
                           "centrality": n["centrality"]} for n in nodes},
                communities=[{"community_id": c.community_id, "name": c.name,
                              "size": c.size, "top_members": c.top_members}
                             for c in analytics.communities])
            if purge:
                db.purge(purge)

            new_manifest = {rel: sha[rel] for rel in included}
            for rel in absent:
                if manifest.get(rel) is not None:
                    new_manifest[rel] = manifest[rel]
            self._save_manifest(new_manifest)

            return {
                "vault": str(self.vault_root),
                "notes_seen": len(included),
                "unreadable": len(unreadable),
                "changed": len(changed),
                "absent_marked": len(absent),
                "purged": len(purge),
                "embedded": embedded,
                "semantic_edges": len(semantic_edges),
                "communities": len(analytics.communities),
                "duration_s": round(time.time() - started, 3),
                "qdrant_ok": qdrant_ok,
            }
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            lock_fh.close()
