"""Dijkstra con heapq; retorna distancias y el reconstruido path."""
import heapq
from typing import Dict, List, Tuple

WeightedGraph = Dict[str, Dict[str, float]]


def dijkstra(graph: WeightedGraph, source: str, target: str) -> Tuple[List[str], float]:
    """Shortest path from source to target. Returns (path, cost).

    Raises ValueError on negative weights; KeyError on unknown nodes.
    """
    if source not in graph or target not in graph:
        raise KeyError("unknown node")
    dist = {source: 0.0}
    prev: Dict[str, str] = {}
    visited = set()
    pq: List[Tuple[float, str]] = [(0.0, source)]
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        if u == target:
            break
        for v, w in graph.get(u, {}).items():
            if w < 0:
                raise ValueError("negative weight not allowed")
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    if target not in visited:
        return [], float("inf")
    path = [target]
    while path[-1] != source:
        path.append(prev[path[-1]])
    path.reverse()
    return path, dist[target]
