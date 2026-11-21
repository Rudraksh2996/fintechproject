"""Directed account graph statistics. Count each simple cycle once at its smallest ID."""

from collections import Counter, defaultdict
from collections.abc import Iterable

import networkx as nx  # type: ignore[import-untyped]
import numpy as np


def _paths(adjacency: dict[int, set[int]], root: int) -> Iterable[tuple[int, ...]]:
    for a in adjacency[root]:
        if a <= root:
            continue
        yield (a,)
        for b in adjacency[a]:
            if b <= root or b == a:
                continue
            yield (a, b)
            for c in adjacency[b]:
                if c > root and c != a and c != b:
                    yield (a, b, c)


def cycle_counts(graph: nx.DiGraph) -> Counter[int]:
    forward = {n: set(graph.successors(n)) for n in graph}
    reverse = {n: set(graph.predecessors(n)) for n in graph}
    counts: Counter[int] = Counter()
    for root in graph:
        ends: defaultdict[tuple[int, int], list[tuple[int, ...]]] = defaultdict(list)
        for path in _paths(reverse, root):
            ends[len(path), path[-1]].append(path[:-1])
        for path in _paths(forward, root):
            # Unique midpoint: forward half has floor(length / 2) edges.
            for size in (len(path), len(path) + 1):
                for tail in ends.get((size, path[-1]), ()):
                    if not any(v in path for v in tail):
                        counts.update((root, *path, *tail))
    return counts


def pagerank(graph: nx.DiGraph) -> dict[int, float]:
    nodes = list(graph)
    if not nodes:
        return {}
    index = {n: i for i, n in enumerate(nodes)}
    src = np.array([index[a] for a, b in graph.edges], dtype=int)
    dst = np.array([index[b] for a, b in graph.edges], dtype=int)
    weight = np.array([data["weight"] for _, _, data in graph.edges(data=True)], dtype=float)
    n = len(nodes)
    out = np.bincount(src, weights=weight, minlength=n)
    transitions = weight / out[src]
    rank = np.full(n, 1 / n)
    for _ in range(200):
        new = (0.15 + 0.85 * rank[out == 0].sum()) / n + 0.85 * np.bincount(
            dst, weights=rank[src] * transitions, minlength=n
        )
        if np.abs(new - rank).sum() < 1e-9:
            return dict(zip(nodes, map(float, new), strict=True))
        rank = new
    raise RuntimeError("Weighted PageRank failed to converge")
