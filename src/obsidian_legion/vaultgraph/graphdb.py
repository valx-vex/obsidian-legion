"""SQLite graph store for the R5 semantic vault (pure stdlib).

Schema v1: ``nodes``, ``edges``, ``communities``, ``meta`` and an FTS5 virtual
table over (title, body) when this interpreter's sqlite supports FTS5 —
otherwise a plain table scored with LIKE (a weighted title/body scorer that
mirrors ``wiki_store.WikiStore.search``). ``rebuild`` writes a fresh DB to a
temp file in the same directory and ``os.replace``s it into place (atomic).
Absent notes are MASKED (``absent_since`` stamped), never deleted — except
``purge`` (the ``.murphy_private`` hard-exclusion escape hatch), which removes
nodes + edges + fts rows outright. No heavy deps: import-safe in the live MCP
server without the [vaultgraph] extra.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from collections import deque
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

_WORD = re.compile(r"[\w]+", re.UNICODE)


def fts_available() -> bool:
    """True iff this interpreter's sqlite3 can create an FTS5 table."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def _fts_query(query: str) -> str:
    tokens = _WORD.findall(query.lower())
    if not tokens:
        return ""
    return " OR ".join(f'"{tok}"' for tok in tokens)


def _create_schema(conn: sqlite3.Connection, fts: bool) -> None:
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT,
            canonical_key TEXT, path TEXT, mtime REAL, sha256 TEXT,
            community_id INTEGER, centrality REAL, pagerank REAL,
            absent_since REAL);
        CREATE INDEX idx_nodes_key ON nodes(canonical_key);
        CREATE INDEX idx_nodes_kind ON nodes(kind);
        CREATE INDEX idx_nodes_comm ON nodes(community_id);
        CREATE TABLE edges (
            src TEXT NOT NULL, dst TEXT NOT NULL, kind TEXT NOT NULL,
            weight REAL, annotation TEXT);
        CREATE INDEX idx_edges_src ON edges(src);
        CREATE INDEX idx_edges_dst ON edges(dst);
        CREATE TABLE communities (
            community_id INTEGER PRIMARY KEY, name TEXT, size INTEGER,
            top_members_json TEXT);
        """
    )
    if fts:
        conn.execute("CREATE VIRTUAL TABLE fts USING fts5(id UNINDEXED, title, body)")
    else:
        conn.execute("CREATE TABLE fts (id TEXT PRIMARY KEY, title TEXT, body TEXT)")
    conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
                 (str(SCHEMA_VERSION),))
    conn.execute("INSERT INTO meta(key, value) VALUES ('fts_enabled', ?)",
                 ("1" if fts else "0"))


def _node_dict(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "kind": row["kind"], "title": row["title"],
            "canonical_key": row["canonical_key"], "path": row["path"],
            "mtime": row["mtime"], "sha256": row["sha256"],
            "community_id": row["community_id"], "centrality": row["centrality"],
            "pagerank": row["pagerank"], "absent_since": row["absent_since"]}


class GraphDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _fts_enabled(conn: sqlite3.Connection) -> bool:
        row = conn.execute("SELECT value FROM meta WHERE key='fts_enabled'").fetchone()
        return bool(row) and row[0] == "1"

    def _resolve_node(self, conn: sqlite3.Connection, key: str):
        for col in ("id", "canonical_key", "path"):
            row = conn.execute(
                f"SELECT * FROM nodes WHERE {col}=? LIMIT 1", (key,)).fetchone()
            if row:
                return row
        return None

    @staticmethod
    def _fetch_nodes(conn: sqlite3.Connection, ids, include_absent: bool) -> list[dict]:
        ids = list(ids)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT * FROM nodes WHERE id IN ({placeholders})", ids).fetchall()
        out: list[dict] = []
        for row in rows:
            if not include_absent and row["absent_since"] is not None:
                continue
            out.append(_node_dict(row))
        return out

    def rebuild(self, nodes: list[dict], edges: list[dict],
                fts_rows: list[dict]) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        fts = fts_available()
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.db_path.parent), prefix=".graph-", suffix=".sqlite")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            conn = sqlite3.connect(tmp_path)
            try:
                _create_schema(conn, fts)
                conn.executemany(
                    "INSERT OR REPLACE INTO nodes "
                    "(id, kind, title, canonical_key, path, mtime, sha256, "
                    "community_id, centrality, pagerank, absent_since) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [(n.get("id"), n.get("kind"), n.get("title"),
                      n.get("canonical_key"), n.get("path"), n.get("mtime"),
                      n.get("sha256"), n.get("community_id"), n.get("centrality"),
                      n.get("pagerank"), n.get("absent_since")) for n in nodes])
                conn.executemany(
                    "INSERT INTO edges (src, dst, kind, weight, annotation) "
                    "VALUES (?,?,?,?,?)",
                    [(e.get("src"), e.get("dst"), e.get("kind"),
                      e.get("weight"), e.get("annotation")) for e in edges])
                conn.executemany(
                    "INSERT INTO fts (id, title, body) VALUES (?,?,?)",
                    [(r.get("id"), r.get("title"), r.get("body")) for r in fts_rows])
                conn.commit()
            finally:
                conn.close()
            os.replace(tmp_path, self.db_path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    def mark_absent(self, relpaths: list[str], ts: float) -> None:
        if not relpaths:
            return
        with self._connect() as conn:
            conn.executemany(
                "UPDATE nodes SET absent_since=? WHERE id=? AND kind='note'",
                [(float(ts), rp) for rp in relpaths])
            conn.commit()

    def purge(self, relpaths: list[str]) -> None:
        if not relpaths:
            return
        with self._connect() as conn:
            for rp in relpaths:
                conn.execute("DELETE FROM edges WHERE src=? OR dst=?", (rp, rp))
                conn.execute("DELETE FROM nodes WHERE id=?", (rp,))
                conn.execute("DELETE FROM fts WHERE id=?", (rp,))
            conn.commit()

    def set_analytics(self, node_updates: dict[str, dict],
                      communities: list[dict] | None = None) -> None:
        with self._connect() as conn:
            for node_id, upd in (node_updates or {}).items():
                conn.execute(
                    "UPDATE nodes SET "
                    "community_id=COALESCE(?, community_id), "
                    "centrality=COALESCE(?, centrality), "
                    "pagerank=COALESCE(?, pagerank) WHERE id=?",
                    (upd.get("community_id"), upd.get("centrality"),
                     upd.get("pagerank"), node_id))
            if communities is not None:
                conn.execute("DELETE FROM communities")
                conn.executemany(
                    "INSERT OR REPLACE INTO communities "
                    "(community_id, name, size, top_members_json) VALUES (?,?,?,?)",
                    [(c.get("community_id"), c.get("name"), c.get("size"),
                      json.dumps(c.get("top_members") or []))
                     for c in communities])
            conn.commit()

    def search_lexical(self, query: str, k: int = 8,
                       include_absent: bool = False) -> list[dict]:
        if not self.db_path.exists():
            return []
        with self._connect() as conn:
            if self._fts_enabled(conn):
                return self._search_fts(conn, query, k, include_absent)
            return self._search_like(conn, query, k, include_absent)

    def _search_fts(self, conn, query, k, include_absent) -> list[dict]:
        match = _fts_query(query)
        if not match:
            return []
        sql = ("SELECT f.id AS id, n.title AS title, n.path AS path, "
               "bm25(fts) AS rank, "
               "snippet(fts, 2, '[', ']', ' … ', 12) AS snippet "
               "FROM fts f JOIN nodes n ON n.id=f.id WHERE fts MATCH ? ")
        if not include_absent:
            sql += "AND n.absent_since IS NULL "
        sql += "ORDER BY rank LIMIT ?"
        rows = conn.execute(sql, (match, k)).fetchall()
        return [{"id": r["id"], "title": r["title"], "path": r["path"],
                 "score": -float(r["rank"]), "snippet": r["snippet"]} for r in rows]

    def _search_like(self, conn, query, k, include_absent) -> list[dict]:
        tokens = _WORD.findall(query.lower())
        if not tokens:
            return []
        sql = ("SELECT f.id AS id, n.title AS ntitle, n.path AS path, "
               "f.title AS ftitle, f.body AS body "
               "FROM fts f JOIN nodes n ON n.id=f.id ")
        if not include_absent:
            sql += "WHERE n.absent_since IS NULL"
        scored: list[tuple[int, dict]] = []
        for r in conn.execute(sql).fetchall():
            title = (r["ftitle"] or "").lower()
            body = (r["body"] or "").lower()
            score = 0
            for tok in tokens:
                if tok in title:
                    score += 10
                if tok in body:
                    score += 1
            if score > 0:
                snippet = (r["body"] or "")[:160]
                scored.append((score, {"id": r["id"], "title": r["ntitle"],
                                       "path": r["path"], "score": float(score),
                                       "snippet": snippet}))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:k]]

    def neighbors(self, key: str, depth: int = 1, kinds: list[str] | None = None,
                  include_absent: bool = False) -> dict:
        empty = {"center": None, "nodes": [], "edges": []}
        if not self.db_path.exists():
            return empty
        kinds_set = set(kinds) if kinds else None
        with self._connect() as conn:
            center = self._resolve_node(conn, key)
            if center is None:
                return empty
            center_id = center["id"]
            visited = {center_id}
            frontier = {center_id}
            edge_keys: set = set()
            collected: list[dict] = []
            for _ in range(max(1, int(depth))):
                if not frontier:
                    break
                placeholders = ",".join("?" for _ in frontier)
                params = list(frontier)
                rows = conn.execute(
                    f"SELECT src, dst, kind, weight, annotation FROM edges "
                    f"WHERE src IN ({placeholders}) OR dst IN ({placeholders})",
                    params + params).fetchall()
                new_frontier: set = set()
                for r in rows:
                    if kinds_set and r["kind"] not in kinds_set:
                        continue
                    ekey = (r["src"], r["dst"], r["kind"])
                    if ekey not in edge_keys:
                        edge_keys.add(ekey)
                        collected.append({"src": r["src"], "dst": r["dst"],
                                          "kind": r["kind"], "weight": r["weight"],
                                          "annotation": r["annotation"]})
                    for other in (r["src"], r["dst"]):
                        if other not in visited:
                            new_frontier.add(other)
                visited |= new_frontier
                frontier = new_frontier
            nodes = self._fetch_nodes(conn, visited, include_absent)
            present = {n["id"] for n in nodes}
            edges = [e for e in collected
                     if e["src"] in present and e["dst"] in present]
            center_dict = next((n for n in nodes if n["id"] == center_id),
                               _node_dict(center))
            return {"center": center_dict, "nodes": nodes, "edges": edges}

    def shortest_path(self, a: str, b: str) -> list[dict]:
        if not self.db_path.exists():
            return []
        with self._connect() as conn:
            na = self._resolve_node(conn, a)
            nb = self._resolve_node(conn, b)
            if na is None or nb is None:
                return []
            start, goal = na["id"], nb["id"]
            if start == goal:
                return [_node_dict(na)]
            prev: dict = {start: None}
            queue = deque([start])
            found = False
            while queue and not found:
                cur = queue.popleft()
                rows = conn.execute(
                    "SELECT src, dst FROM edges WHERE src=? OR dst=?",
                    (cur, cur)).fetchall()
                for r in rows:
                    nxt = r["dst"] if r["src"] == cur else r["src"]
                    if nxt not in prev:
                        prev[nxt] = cur
                        if nxt == goal:
                            found = True
                            break
                        queue.append(nxt)
            if goal not in prev:
                return []
            chain: list[str] = []
            node = goal
            while node is not None:
                chain.append(node)
                node = prev[node]
            chain.reverse()
            placeholders = ",".join("?" for _ in chain)
            by_id = {row["id"]: _node_dict(row) for row in conn.execute(
                f"SELECT * FROM nodes WHERE id IN ({placeholders})", chain)}
            return [by_id[i] for i in chain if i in by_id]

    def communities(self) -> list[dict]:
        if not self.db_path.exists():
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT community_id, name, size, top_members_json FROM communities "
                "ORDER BY size DESC, community_id ASC").fetchall()
        return [{"community_id": r["community_id"], "name": r["name"],
                 "size": r["size"],
                 "top_members": json.loads(r["top_members_json"] or "[]")}
                for r in rows]

    def stats(self) -> dict:
        if not self.db_path.exists():
            return {"exists": False, "nodes": 0, "edges": 0, "communities": 0,
                    "absent": 0, "kinds": {}, "fts_enabled": False,
                    "schema_version": None}
        with self._connect() as conn:
            nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            comms = conn.execute("SELECT COUNT(*) FROM communities").fetchone()[0]
            absent = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE absent_since IS NOT NULL"
            ).fetchone()[0]
            kinds = {row[0]: row[1] for row in conn.execute(
                "SELECT kind, COUNT(*) FROM nodes GROUP BY kind")}
            sv = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'").fetchone()
            return {"exists": True, "nodes": nodes, "edges": edges,
                    "communities": comms, "absent": absent, "kinds": kinds,
                    "fts_enabled": self._fts_enabled(conn),
                    "schema_version": int(sv[0]) if sv else None}
