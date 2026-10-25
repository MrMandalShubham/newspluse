"""Clustering — group articles by embedding similarity (same product / topic).

Uses numpy-vectorised cosine similarity for speed (milliseconds on 3k+ articles).
Deterministic for a fixed input order, which makes it straightforward to test.
"""

import numpy as np


def greedy_cluster(
    items: list[tuple[int, list[float]]], threshold: float, linkage: str = "single"
) -> list[list[int]]:
    """Group items whose vectors are within ``threshold`` cosine similarity.

    ``items`` is (id, vector). An item joins an existing cluster if it is similar
    enough, otherwise it starts a new one. ``linkage`` controls the comparison:

      * ``"single"``   — similar to ANY member (max). Simple, but chains.
      * ``"centroid"`` — similar to the cluster's MEAN vector. Resists chaining.

    Returns clusters as lists of ids, preserving input order.
    """
    if not items:
        return []

    ids = [i for i, _ in items]
    vecs = np.array([v for _, v in items], dtype=np.float64)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = vecs / norms

    clusters: list[dict] = []
    for idx in range(len(ids)):
        u = unit[idx]
        best_idx: int | None = None
        best_sim = threshold

        if clusters:
            if linkage == "centroid":
                centroids = np.array(
                    [cl["sum"] / cl["count"] for cl in clusters], dtype=np.float64,
                )
                c_norms = np.linalg.norm(centroids, axis=1, keepdims=True)
                c_norms[c_norms == 0] = 1.0
                sims = centroids @ u / c_norms.ravel()
                max_i = int(np.argmax(sims))
                if sims[max_i] >= best_sim:
                    best_sim = float(sims[max_i])
                    best_idx = max_i
            else:
                for ci, cl in enumerate(clusters):
                    member_unit = np.array(cl["units"], dtype=np.float64)
                    sim = float(np.max(member_unit @ u))
                    if sim >= best_sim:
                        best_sim = sim
                        best_idx = ci

        if best_idx is None:
            clusters.append({
                "ids": [ids[idx]],
                "units": [u.tolist()],
                "sum": vecs[idx].copy(),
                "count": 1,
            })
        else:
            cl = clusters[best_idx]
            cl["ids"].append(ids[idx])
            cl["units"].append(u.tolist())
            cl["sum"] = cl["sum"] + vecs[idx]
            cl["count"] += 1

    return [cl["ids"] for cl in clusters]
