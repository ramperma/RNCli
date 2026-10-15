"""Dijkstra con heap binario; devuelve (path, costo). Sin pesos negativos."""
import heapq
from typing import Dict, List, Tuple

Graph = Dict[str, Dict[str, float]]


def shortest_path(graph: Graph, src: str, dst: str) -> Tuple[List[str], float]:
    if src not in graph or dst not in graph:
        raise KeyError("node not in graph")
    dist: Dict[str, float] = {src: 0.0}
    parent: Dict[str, str] = {}
    done: set[str] = set()
    heap: List[Tuple[float, str]] = [(0.0, src)]
    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        for v, w in graph[u].items():
            if w < 0:
                raise ValueError("negative edge weight")
            alt = d + w
            if alt < dist.get(v, float("inf")):
                dist[v] = alt
                parent[v] = u
                heapq.heappush(heap, (alt, v))
    if dst not in done:
        return [], float("inf")
    path = [dst]
    while path[0] != src:
        path.insert(0, parent[path[0]])
    return path, dist[dst]
