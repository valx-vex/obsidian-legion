from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass
class CommunityInfo:
    community_id: int
    name: str
    size: int
    top_members: list[str]


@dataclass
class AnalyticsResult:
    community_of: dict[str, int]
    pagerank: dict[str, float]
    centrality: dict[str, float]
    communities: list[CommunityInfo]


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "are", "was",
    "you", "your", "our", "not", "but", "have", "has", "had", "all",
    "any", "can", "will", "into", "out", "off", "its", "it", "a", "an",
    "of", "to", "in", "on", "is", "be", "or", "as", "at", "by", "md",
})


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower())
            if len(t) > 2 and t not in _STOPWORDS]


def compute_analytics(nodes: list[dict], edges: list[dict],
                      betweenness_k: int = 256, seed: int = 42) -> AnalyticsResult:
    import networkx as nx  # heavy import kept inside the function

    ids = [str(node["id"]) for node in nodes]
    title_by_id = {str(node["id"]): (node.get("title") or str(node["id"])) for node in nodes}

    graph = nx.Graph()
    graph.add_nodes_from(ids)
    for edge in edges:
        src, dst = edge.get("src"), edge.get("dst")
        if src is None or dst is None:
            continue
        src, dst = str(src), str(dst)
        weight = float(edge.get("weight") or 1.0)
        if graph.has_edge(src, dst):
            graph[src][dst]["weight"] += weight
        else:
            graph.add_edge(src, dst, weight=weight)
        title_by_id.setdefault(src, src)
        title_by_id.setdefault(dst, dst)

    n = graph.number_of_nodes()
    if n == 0:
        return AnalyticsResult({}, {}, {}, [])

    # PageRank — weighted, deterministic given the graph.
    try:
        pagerank = nx.pagerank(graph, weight="weight")
    except Exception:
        pagerank = {node: 1.0 / n for node in graph.nodes()}

    # Betweenness — k-sampled (min(k, n)), UNWEIGHTED, seeded.
    k = min(betweenness_k, n)
    centrality = nx.betweenness_centrality(graph, k=k, weight=None,
                                           normalized=True, seed=seed)

    # Louvain communities — seeded, then re-indexed deterministically.
    raw = nx.community.louvain_communities(graph, weight="weight", seed=seed)
    ordered = sorted([sorted(str(m) for m in community) for community in raw])
    community_of: dict[str, int] = {}
    for cid, members in enumerate(ordered):
        for node in members:
            community_of[node] = cid

    num_comms = len(ordered)
    df: dict[str, int] = {}
    per_comm_tokens: list[dict[str, int]] = []
    for members in ordered:
        counts: dict[str, int] = {}
        for node in members:
            for token in _tokens(title_by_id.get(node, node)):
                counts[token] = counts.get(token, 0) + 1
        per_comm_tokens.append(counts)
        for token in counts:
            df[token] = df.get(token, 0) + 1

    communities: list[CommunityInfo] = []
    for cid, members in enumerate(ordered):
        counts = per_comm_tokens[cid]

        def _score(item):
            term, tf = item
            idf = math.log((num_comms + 1) / (df[term] + 1))
            return (-(tf * idf), term)

        top_terms = [term for term, _ in sorted(counts.items(), key=_score)[:3]]
        top_members = sorted(members, key=lambda node: (-pagerank.get(node, 0.0), node))[:5]
        top_titles = [title_by_id.get(node, node) for node in top_members[:2]]
        name_parts = list(top_terms)
        for title in top_titles:
            if title and title.lower() not in [t.lower() for t in name_parts]:
                name_parts.append(title)
        name = ", ".join(dict.fromkeys(p for p in name_parts if p)) or f"community-{cid}"
        communities.append(CommunityInfo(community_id=cid, name=name,
                                          size=len(members), top_members=top_members))

    return AnalyticsResult(community_of=community_of, pagerank=pagerank,
                           centrality=centrality, communities=communities)
