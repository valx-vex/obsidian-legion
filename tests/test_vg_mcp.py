import json
from pathlib import Path

import pytest

from obsidian_legion import mcp_server
from obsidian_legion.config import LegionPaths

EXISTING_TOOLS = {
    "capture_task", "list_tasks", "next_tasks", "claim_task", "complete_task",
    "refresh_dashboards", "wiki_bootstrap", "wiki_ingest", "wiki_compile",
    "wiki_compile_vault", "wiki_compile_public", "wiki_export", "wiki_search",
    "wiki_status", "wiki_list", "graphify_build", "graphify_query",
}
NEW_TOOLS = {
    "vault_search", "vault_neighbors", "vault_path",
    "vault_communities", "vault_page", "vault_stats",
}


class _NullEmbedder:
    def search(self, query, k=8, include_absent=False):
        return []


class _BuildEmbedder:
    def ensure_collection(self):
        pass

    def upsert_notes(self, notes):
        return len(notes)

    def mark_absent(self, relpaths, ts):
        pass

    def delete_points(self, relpaths):
        pass

    def knn_edges(self, k=8, related_min=0.60, near_dup_min=0.92):
        return []

    def search(self, query, k=8, include_absent=False):
        return []


def _task_vault(tmp_path):
    vault = tmp_path / "cvault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "06-daily" / "action-points").mkdir(parents=True)
    return vault


def _graph_vault(tmp_path):
    from obsidian_legion.vaultgraph.builder import GraphBuilder

    vault = tmp_path / "gvault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "apple.md").write_text("# Apple\n[[banana]] #fruit\n", encoding="utf-8")
    (vault / "banana.md").write_text("# Banana\n[[apple]] #fruit\n", encoding="utf-8")
    GraphBuilder(vault, embedder=_BuildEmbedder()).update(full=True)
    (vault / "wiki").mkdir(parents=True, exist_ok=True)
    (vault / "wiki" / "index.md").write_text("# VEXPEDIA\n", encoding="utf-8")
    return vault


def _server(tmp_path):
    return mcp_server.build_mcp(LegionPaths.discover(_task_vault(tmp_path)))


def _fn(server, name):
    return server._tool_manager._tools[name].fn


def test_all_tools_register(tmp_path):
    server = _server(tmp_path)
    names = set(server._tool_manager._tools)
    assert EXISTING_TOOLS <= names          # 17 existing survive
    assert NEW_TOOLS <= names                # 6 new added
    assert len(names) >= 23


def test_vault_search_missing_deps(tmp_path, monkeypatch):
    server = _server(tmp_path)

    def boom(vault):
        raise ImportError("no networkx")

    monkeypatch.setattr(mcp_server, "_resolve_vault", boom)
    assert _fn(server, "vault_search")("q") == {"error": "vaultgraph extras not installed"}


def test_vault_stats_not_built(tmp_path, monkeypatch):
    server = _server(tmp_path)
    empty = tmp_path / "empty"
    (empty / ".obsidian").mkdir(parents=True)
    monkeypatch.setattr(mcp_server, "_resolve_vault", lambda vault: empty)
    out = _fn(server, "vault_stats")()
    assert out["error"] == "graph not built yet"
    assert "hint" in out


def test_vault_search_hybrid_dedup(tmp_path, monkeypatch):
    gvault = _graph_vault(tmp_path)
    server = _server(tmp_path)
    monkeypatch.setattr(mcp_server, "_resolve_vault", lambda vault: gvault)

    class FakeEmb:
        def search(self, query, k=8, include_absent=False):
            return [{"path": "apple.md", "score": 0.99},
                    {"path": "zzz.md", "score": 0.5}]

    monkeypatch.setattr(mcp_server, "_graph_embedder", lambda root: FakeEmb())
    out = _fn(server, "vault_search")("Apple", k=8)
    paths = [r["path"] for r in out["results"]]
    assert "apple.md" in paths
    assert paths.count("apple.md") == 1          # deduped across lexical + semantic
    assert "zzz.md" in paths                     # semantic-only hit merged in


def test_graph_readonly_tools(tmp_path, monkeypatch):
    gvault = _graph_vault(tmp_path)
    server = _server(tmp_path)
    monkeypatch.setattr(mcp_server, "_resolve_vault", lambda vault: gvault)
    monkeypatch.setattr(mcp_server, "_graph_embedder", lambda root: _NullEmbedder())

    stats = _fn(server, "vault_stats")()
    assert isinstance(stats, dict) and "error" not in stats
    comms = _fn(server, "vault_communities")()
    assert "communities" in comms and "error" not in comms
    neighbors = _fn(server, "vault_neighbors")("apple.md")
    assert "error" not in neighbors
    path = _fn(server, "vault_path")("apple.md", "banana.md")
    assert "path" in path and "error" not in path


def test_vault_page(tmp_path, monkeypatch):
    gvault = _graph_vault(tmp_path)
    server = _server(tmp_path)
    monkeypatch.setattr(mcp_server, "_resolve_vault", lambda vault: gvault)
    monkeypatch.setattr(mcp_server, "_graph_embedder", lambda root: _NullEmbedder())

    page = _fn(server, "vault_page")("index.md")
    assert "VEXPEDIA" in page["content"]
    missing = _fn(server, "vault_page")("nope.md")
    assert "error" in missing


def test_wiki_deep_search_delegates_to_vaultgraph(tmp_path, monkeypatch):
    """spec §6.3: legacy deep search rides the MiniLM-384 contract now."""
    from obsidian_legion import wiki_store as ws

    calls = {}

    class _FakeEmbedder:
        def __init__(self, qdrant_url, collection):
            calls["collection"] = collection

        def search(self, query, k):
            calls["query"], calls["k"] = query, k
            return [{"id": "n", "title": "T", "path": "a.md",
                     "score": 0.9, "snippet": "s"}]

    import obsidian_legion.vaultgraph.embedder as emb
    monkeypatch.setattr(emb, "VaultEmbedder", _FakeEmbedder)
    store = ws.WikiStore.__new__(ws.WikiStore)          # no full init needed
    store.paths = type("P", (), {"qdrant_url": "http://x:1",
                                 "qdrant_collection": "vault_eternal"})()
    hits = ws.WikiStore._qdrant_search(store, "flame", 3)
    assert calls == {"collection": "vault_eternal", "query": "flame", "k": 3}
    assert hits and hits[0]["path"] == "a.md"
