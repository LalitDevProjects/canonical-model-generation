"""
Minimal hand-rolled graph utilities for clustering (Section 9.4-9.5).
No third-party graph library dependency - every dependency this repo has
added so far (lxml, psycopg, anthropic) was load-bearing/non-substitutable,
and PoC block sizes (<=40 members, Section 8.6's own prompt-size ceiling)
make BFS-based connected components trivial to hand-write, keep
mypy --strict clean, and stay hermetically testable without a large
third-party surface.

Shared by algorithms/clustering.py (top-level component detection across
a block's similarity edges) and algorithms/conflict.py (component
detection within a shrinking edge set as min_cut_until removes edges).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def connected_components(ids: Sequence[str], edges: Mapping[frozenset[str], float]) -> list[list[str]]:
    """BFS connected components over `ids`, restricted to `edges` whose
    both endpoints are in `ids`. Deterministic: neighbours are visited in
    sorted order, and components (and their own members) are returned in
    sorted order - reproducibility is a requirement here, not a nicety
    (Section 8.4's own framing, applied throughout this repo)."""
    adjacency: dict[str, set[str]] = {i: set() for i in ids}
    id_set = set(ids)
    for pair in edges:
        a, b = tuple(pair)
        if a in id_set and b in id_set:
            adjacency[a].add(b)
            adjacency[b].add(a)

    visited: set[str] = set()
    components: list[list[str]] = []
    for start in sorted(ids):
        if start in visited:
            continue
        component: list[str] = []
        queue = [start]
        visited.add(start)
        while queue:
            current = queue.pop(0)
            component.append(current)
            for neighbour in sorted(adjacency[current]):
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append(neighbour)
        components.append(sorted(component))
    return components
