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
    items: list[tuple[int, list[float]]], threshold: float, linkage: str = "single"
) -> list[list[int]]:
    """Group items whose vectors are within ``threshold`` cosine similarity.

    ``items`` is (id, vector). An item joins an existing cluster if it is similar
    enough, otherwise it starts a new one. ``linkage`` controls the comparison:

      * ``"single"``   — similar to ANY member (max). Simple, but chains
                         (A~B, B~C pulls A,B,C together even if A is unlike C),
                         which collapses large corpora into one mega-cluster.
      * ``"centroid"`` — similar to the cluster's MEAN vector. Resists chaining,
                         so it scales to thousands of articles. Also cheaper
                         (one comparison per cluster, not per member).

    Returns clusters as lists of ids, preserving input order.
    """
    clusters: list[dict] = []
    for id_, vec in items:
        best: dict | None = None
        best_sim = threshold
        for cl in clusters:
            if linkage == "centroid":
                n = cl["count"]
                sim = cosine(vec, [s / n for s in cl["sum"]])
            else:
                sim = max(cosine(vec, v) for v in cl["vecs"])
            if sim >= best_sim:
                best_sim = sim
                best = cl
        if best is None:
            clusters.append({"ids": [id_], "vecs": [vec], "sum": list(vec), "count": 1})
        else:
            best["ids"].append(id_)
            best["vecs"].append(vec)
            best["sum"] = [s + v for s, v in zip(best["sum"], vec, strict=False)]
            best["count"] += 1
    return [cl["ids"] for cl in clusters]
