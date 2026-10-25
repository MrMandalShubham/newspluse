"""Summarization pipeline: raw_items -> article_reports.

For each raw item without a report, load its stored body, classify + summarize
via the summarizer, and persist an ``article_reports`` row. Idempotent (skips
already-summarized items); audited in ``job_runs``. Embedding + clustering are
added in later steps.
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from newspulse.config import settings
from newspulse.db import SessionLocal
from newspulse.models import ArticleReport, JobRun, RawItem, ReportCluster
from newspulse.reports.cluster import greedy_cluster
from newspulse.reports.embedder import Embedder
from newspulse.reports.merger import ClusterMerger, MergedStory
from newspulse.reports.summarizer import Summarizer
from newspulse.storage import ObjectStorage, get_storage

DEFAULT_THRESHOLD = 0.92
MERGE_MAX_MEMBERS = 12
MERGE_MAX_WORKERS = 8


class _MergeRateLimiter:
    """Token-bucket rate limiter for cluster merge Mistral calls (thread-safe)."""

    def __init__(self, calls_per_second: float = 5.0) -> None:
        self._interval = 1.0 / calls_per_second
        self._lock = threading.Lock()
        self._last = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._last + self._interval - now
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


_merge_limiter = _MergeRateLimiter(calls_per_second=5.0)


def _storage_key(raw_ref: str | None) -> str:
    return (raw_ref or "").split("://", 1)[-1]


def _pending(session: Session) -> list[RawItem]:
    stmt = select(RawItem).where(
        ~select(ArticleReport.id).where(ArticleReport.raw_item_id == RawItem.id).exists()
    )
    return list(session.execute(stmt).scalars().all())


def summarize_pending(
    summarizer: Summarizer,
    session: Session | None = None,
    storage: ObjectStorage | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Summarize all un-summarized raw items. Returns counts."""
    own_session = session is None
    session = session or SessionLocal()
    storage = storage or get_storage()

    job = JobRun(job_name="summarize", status="started")
    session.add(job)
    session.flush()

    processed = relevant = errors = tokens = 0
    try:
        items = _pending(session)
        if limit is not None:
            items = items[:limit]
        for item in items:
            try:
                payload = json.loads(storage.get(_storage_key(item.raw_ref)))
            except Exception:  # noqa: BLE001 - missing/broken payload, skip
                continue
            try:
                result = summarizer.summarize(
                    payload.get("title"), payload.get("body") or "", payload.get("keywords") or []
                )
            except Exception:  # noqa: BLE001 - LLM failed after retries; skip item
                errors += 1
                continue

            usage = getattr(summarizer, "last_usage", None)
            if usage:
                tokens += int(usage.get("total_tokens") or 0)

            session.add(
                ArticleReport(
                    raw_item_id=item.id,
                    is_product_related=result.is_product_related,
                    title=result.label or item.title,
                    summary=result.summary or None,
                    category=result.category or None,
                    sentiment=result.sentiment or None,
                    theme=result.theme or None,
                    event_types=result.event_types,
                    importance_score=result.importance_score or None,
                    country=result.country or None,
                    brands=result.brands,
                    companies=result.companies,
                    ingredients=result.ingredients,
                    products=result.products,
                    model=settings.mistral_model,
                )
            )
            processed += 1
            if result.is_product_related:
                relevant += 1

        stats = {"processed": processed, "relevant": relevant, "errors": errors, "tokens": tokens}
        job.status = "success"
        job.finished_at = datetime.now(UTC)
        job.stats = stats
        session.commit()
        return stats
    except Exception as exc:
        session.rollback()
        failed = JobRun(
            job_name="summarize", status="failed", error=str(exc), finished_at=datetime.now(UTC)
        )
        session.add(failed)
        session.commit()
        raise
    finally:
        if own_session:
            session.close()


def embed_pending(
    embedder: Embedder, session: Session | None = None, limit: int | None = None
) -> dict[str, int]:
    """Embed product-related article summaries that don't have an embedding yet."""
    own_session = session is None
    session = session or SessionLocal()
    job = JobRun(job_name="embed", status="started")
    session.add(job)
    session.flush()
    try:
        reports = list(
            session.execute(
                select(ArticleReport).where(
                    ArticleReport.is_product_related.is_(True),
                    ArticleReport.embedding.is_(None),
                )
            ).scalars().all()
        )
        if limit is not None:
            reports = reports[:limit]
        texts = [r.summary or r.title or "" for r in reports]
        vectors = embedder.embed(texts) if texts else []
        for report, vector in zip(reports, vectors, strict=False):
            report.embedding = vector
        stats = {"embedded": len(vectors)}
        job.status = "success"
        job.finished_at = datetime.now(UTC)
        job.stats = stats
        session.commit()
        return stats
    except Exception as exc:
        session.rollback()
        failed = JobRun(
            job_name="embed", status="failed", error=str(exc), finished_at=datetime.now(UTC)
        )
        session.add(failed)
        session.commit()
        raise
    finally:
        if own_session:
            session.close()


def build_clusters(
    session: Session | None = None, threshold: float = DEFAULT_THRESHOLD
) -> dict[str, int]:
    """Incremental clustering: assign unclustered reports to existing clusters,
    then cluster remaining new reports among themselves. Only does a full
    re-cluster when no clusters exist yet."""
    own_session = session is None
    session = session or SessionLocal()
    job = JobRun(job_name="cluster", status="started")
    session.add(job)
    session.flush()
    try:
        existing_clusters = list(
            session.execute(select(ReportCluster)).scalars().all()
        )
        new_reports = list(
            session.execute(
                select(ArticleReport)
                .where(
                    ArticleReport.is_product_related.is_(True),
                    ArticleReport.embedding.is_not(None),
                    ArticleReport.cluster_id.is_(None),
                )
                .order_by(ArticleReport.id)
            ).scalars().all()
        )

        if not new_reports:
            stats = {
                "reports": 0, "clusters": len(existing_clusters),
                "assigned": 0, "new_clusters": 0,
            }
            job.status = "success"
            job.finished_at = datetime.now(UTC)
            job.stats = stats
            session.commit()
            return stats

        if not existing_clusters:
            return _full_recluster(session, job, threshold)

        # --- Incremental: assign new reports to existing cluster centroids ---
        cluster_members: dict[int, list[ArticleReport]] = {}
        for cl in existing_clusters:
            cluster_members[cl.id] = list(
                session.execute(
                    select(ArticleReport).where(ArticleReport.cluster_id == cl.id)
                ).scalars().all()
            )

        centroids: list[tuple[int, np.ndarray]] = []
        for cl in existing_clusters:
            members = cluster_members[cl.id]
            if not members:
                continue
            embeddings = [m.embedding for m in members if m.embedding is not None]
            if embeddings:
                centroid = np.mean(embeddings, axis=0)
                centroids.append((cl.id, centroid))

        if not centroids:
            return _full_recluster(session, job, threshold)

        centroid_ids = [cid for cid, _ in centroids]
        centroid_matrix = np.array([c for _, c in centroids], dtype=np.float64)
        c_norms = np.linalg.norm(centroid_matrix, axis=1, keepdims=True)
        c_norms[c_norms == 0] = 1.0
        centroid_unit = centroid_matrix / c_norms

        assigned = 0
        unmatched: list[ArticleReport] = []

        for report in new_reports:
            vec = np.array(report.embedding, dtype=np.float64)
            norm = np.linalg.norm(vec)
            if norm == 0:
                unmatched.append(report)
                continue
            u = vec / norm
            sims = centroid_unit @ u
            best_i = int(np.argmax(sims))
            if sims[best_i] >= threshold:
                cl_id = centroid_ids[best_i]
                report.cluster_id = cl_id
                cl_obj = next(c for c in existing_clusters if c.id == cl_id)
                cl_obj.size = (cl_obj.size or 0) + 1
                assigned += 1
            else:
                unmatched.append(report)

        new_clusters_count = 0
        if unmatched:
            groups = greedy_cluster(
                [(r.id, r.embedding) for r in unmatched], threshold, linkage="centroid",
            )
            by_id = {r.id: r for r in unmatched}
            for group in groups:
                members = [by_id[i] for i in group]
                cluster = ReportCluster(
                    label=members[0].title or "Untitled", summary="", size=len(members),
                )
                session.add(cluster)
                session.flush()
                for member in members:
                    member.cluster_id = cluster.id
                new_clusters_count += 1

        total_clusters = len(existing_clusters) + new_clusters_count
        stats = {
            "reports": len(new_reports),
            "clusters": total_clusters,
            "assigned": assigned,
            "new_clusters": new_clusters_count,
        }
        job.status = "success"
        job.finished_at = datetime.now(UTC)
        job.stats = stats
        session.commit()
        print(
            f"  [cluster] {assigned} assigned to existing, "
            f"{new_clusters_count} new clusters from {len(unmatched)} unmatched",
            flush=True,
        )
        return stats
    except Exception as exc:
        session.rollback()
        failed = JobRun(
            job_name="cluster", status="failed", error=str(exc), finished_at=datetime.now(UTC)
        )
        session.add(failed)
        session.commit()
        raise
    finally:
        if own_session:
            session.close()


def _full_recluster(
    session: Session, job: JobRun, threshold: float,
) -> dict[str, int]:
    """Full re-cluster from scratch (first run or when forced)."""
    session.query(ArticleReport).update(
        {ArticleReport.cluster_id: None}, synchronize_session=False,
    )
    session.query(ReportCluster).delete(synchronize_session=False)
    session.flush()

    reports = list(
        session.execute(
            select(ArticleReport)
            .where(
                ArticleReport.is_product_related.is_(True),
                ArticleReport.embedding.is_not(None),
            )
            .order_by(ArticleReport.id)
        ).scalars().all()
    )
    by_id = {r.id: r for r in reports}
    groups = greedy_cluster(
        [(r.id, r.embedding) for r in reports], threshold, linkage="centroid",
    )

    for group in groups:
        members = [by_id[i] for i in group]
        cluster = ReportCluster(
            label=members[0].title or "Untitled", summary="", size=len(members),
        )
        session.add(cluster)
        session.flush()
        for member in members:
            member.cluster_id = cluster.id

    stats = {
        "reports": len(reports), "clusters": len(groups),
        "assigned": 0, "new_clusters": len(groups),
    }
    job.status = "success"
    job.finished_at = datetime.now(UTC)
    job.stats = stats
    session.commit()
    print(
        f"  [cluster] full recluster: {len(reports)} reports -> {len(groups)} clusters",
        flush=True,
    )
    return stats


def _merge_one_cluster(
    cluster_id: int,
    label: str,
    members_data: list[dict],
    merger: ClusterMerger,
) -> tuple[int, str, MergedStory | None, dict | None, str | None]:
    """Merge one multi-article cluster via LLM (thread-safe, no DB access)."""
    _merge_limiter.acquire()
    try:
        story = merger.merge(members_data)
        usage = getattr(merger, "last_usage", None)
        return cluster_id, label, story, usage, None
    except Exception as e:  # noqa: BLE001
        return cluster_id, label, None, None, str(e)


def merge_clusters(
    merger: ClusterMerger,
    session: Session | None = None,
    max_workers: int = MERGE_MAX_WORKERS,
) -> dict[str, int]:
    """Fill each cluster's merged summary. Singletons reuse their article summary;
    multi-article clusters are merged by the LLM concurrently."""
    own_session = session is None
    session = session or SessionLocal()
    job = JobRun(job_name="merge", status="started")
    session.add(job)
    session.flush()
    merged = singletons = errors = tokens = 0
    try:
        clusters = list(
            session.execute(
                select(ReportCluster).where(
                    (ReportCluster.summary.is_(None)) | (ReportCluster.summary == "")
                )
            ).scalars().all()
        )
        cluster_map = {cl.id: cl for cl in clusters}

        multi_tasks: list[tuple[int, str, list[dict]]] = []
        for cluster in clusters:
            members = list(
                session.execute(
                    select(ArticleReport).where(
                        ArticleReport.cluster_id == cluster.id,
                    )
                ).scalars().all()
            )
            if not members:
                continue
            if len(members) == 1:
                cluster.summary = members[0].summary or ""
                cluster.label = members[0].title or cluster.label
                singletons += 1
                continue
            sample = members[:MERGE_MAX_MEMBERS]
            members_data = [{"title": m.title, "summary": m.summary} for m in sample]
            multi_tasks.append((cluster.id, cluster.label, members_data))

        if multi_tasks:
            print(
                f"  [merge] {len(multi_tasks)} multi-article clusters "
                f"({max_workers} concurrent)...",
                flush=True,
            )
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(
                        _merge_one_cluster, cid, label, mdata, merger,
                    ): cid
                    for cid, label, mdata in multi_tasks
                }
                for future in as_completed(futures):
                    cid, label, story, usage, err = future.result()
                    cl = cluster_map[cid]
                    if err or story is None:
                        errors += 1
                        cl.summary = cl.summary or ""
                        continue
                    if usage:
                        tokens += int(usage.get("total_tokens") or 0)
                    cl.summary = story.summary or cl.summary or ""
                    cl.label = story.label or cl.label
                    cl.model = settings.mistral_model
                    merged += 1

        stats = {"merged": merged, "singletons": singletons, "errors": errors, "tokens": tokens}
        job.status = "success"
        job.finished_at = datetime.now(UTC)
        job.stats = stats
        session.commit()
        return stats
    except Exception as exc:
        session.rollback()
        failed = JobRun(
            job_name="merge", status="failed", error=str(exc), finished_at=datetime.now(UTC)
        )
        session.add(failed)
        session.commit()
        raise
    finally:
        if own_session:
            session.close()
