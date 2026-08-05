"""Clustering — group articles by embedding similarity (same product / topic).

Pure functions (no DB, no LLM): cosine similarity + single-linkage greedy
clustering with a similarity threshold. Deterministic for a fixed input order,
which makes it straightforward to test.
"""

import math


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def greedy_cluster(
    items: list[tuple[int, list[float]]], threshold: float
) -> list[list[int]]:
    """Group items whose vectors are within ``threshold`` cosine similarity.

    ``items`` is (id, vector). Single-linkage: an item joins an existing cluster
    if it is similar enough to any member; otherwise it starts a new cluster.
    Returns clusters as lists of ids, preserving input order.
    """
    clusters: list[dict] = []
    for id_, vec in items:
        best: dict | None = None
        best_sim = threshold
        for cl in clusters:
            sim = max(cosine(vec, v) for v in cl["vecs"])
            if sim >= best_sim:
                best_sim = sim
                best = cl
        if best is None:
            clusters.append({"ids": [id_], "vecs": [vec]})
        else:
            best["ids"].append(id_)
            best["vecs"].append(vec)
    return [cl["ids"] for cl in clusters]
