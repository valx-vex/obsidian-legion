from obsidian_legion.vaultgraph.analytics import (
    AnalyticsResult,
    CommunityInfo,
    compute_analytics,
)


def _clique(prefix: str, titles: list[str]):
    nodes = [{"id": f"{prefix}{i}", "title": titles[i - 1], "kind": "note"}
             for i in range(1, 5)]
    ids = [n["id"] for n in nodes]
    edges = []
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            edges.append({"src": ids[a], "dst": ids[b], "kind": "wikilink", "weight": 1.0})
    return nodes, edges


def _toy():
    a_nodes, a_edges = _clique("a", ["apple one", "apple two", "apple three", "apple four"])
    b_nodes, b_edges = _clique("b", ["banana one", "banana two", "banana three", "banana four"])
    bridge = {"id": "bridge", "title": "bridge span", "kind": "note"}
    nodes = a_nodes + b_nodes + [bridge]
    edges = a_edges + b_edges + [
        {"src": "bridge", "dst": "a1", "kind": "wikilink", "weight": 1.0},
        {"src": "bridge", "dst": "b1", "kind": "wikilink", "weight": 1.0},
    ]
    return nodes, edges


def test_two_clear_clusters_two_communities():
    nodes, edges = _toy()
    result = compute_analytics(nodes, edges, seed=7)
    assert isinstance(result, AnalyticsResult)
    assert len(result.communities) == 2
    a_comm = {result.community_of[f"a{i}"] for i in range(1, 5)}
    b_comm = {result.community_of[f"b{i}"] for i in range(1, 5)}
    assert len(a_comm) == 1 and len(b_comm) == 1
    assert a_comm != b_comm


def test_bridge_has_top_centrality():
    nodes, edges = _toy()
    result = compute_analytics(nodes, edges, seed=7)
    top = max(result.centrality, key=result.centrality.get)
    assert top == "bridge"


def test_community_names_reflect_tfidf_terms():
    nodes, edges = _toy()
    result = compute_analytics(nodes, edges, seed=7)
    names = " || ".join(c.name for c in result.communities).lower()
    assert "apple" in names
    assert "banana" in names
    assert all(isinstance(c, CommunityInfo) and c.name for c in result.communities)


def test_deterministic_across_runs():
    nodes, edges = _toy()
    r1 = compute_analytics(nodes, edges, seed=7)
    r2 = compute_analytics(nodes, edges, seed=7)
    assert r1.community_of == r2.community_of
    assert [c.name for c in r1.communities] == [c.name for c in r2.communities]
    assert r1.pagerank == r2.pagerank


def test_empty_graph():
    result = compute_analytics([], [])
    assert result.community_of == {}
    assert result.pagerank == {}
    assert result.centrality == {}
    assert result.communities == []


def test_single_node():
    result = compute_analytics([{"id": "solo", "title": "solo", "kind": "note"}], [])
    assert result.community_of == {"solo": 0}
    assert result.communities[0].size == 1
    assert result.centrality["solo"] == 0.0
