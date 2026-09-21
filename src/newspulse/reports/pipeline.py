"""Summarization pipeline: raw_items -> article_reports.

For each raw item without a report, load its stored body, classify + summarize
via the summarizer, and persist an ``article_reports`` row. Idempotent (skips
already-summarized items); audited in ``job_runs``. Embedding + clustering are
added in later steps.
"""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newspulse.config import settings
from newspulse.db import SessionLocal
from newspulse.models import ArticleReport, JobRun, RawItem, ReportCluster
from newspulse.reports.cluster import greedy_cluster
from newspulse.reports.embedder import Embedder
from newspulse.reports.merger import ClusterMerger
from newspulse.reports.summarizer import Summarizer
from newspulse.storage import ObjectStorage, get_storage

DEFAULT_THRESHOLD = 0.92
# Cap how many member summaries are sent to the LLM merge (avoids context overflow
# on large clusters); the cluster's true size is still recorded from all members.
MERGE_MAX_MEMBERS = 12


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
    """Recompute clusters over embedded product reports (merged summaries: step 8.4)."""
    own_session = session is None
    session = session or SessionLocal()
    job = JobRun(job_name="cluster", status="started")
    session.add(job)
    session.flush()
    try:
        # Reset previous clustering (FK: null out members before deleting clusters).
        session.query(ArticleReport).update(
            {ArticleReport.cluster_id: None}, synchronize_session=False
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
            [(r.id, r.embedding) for r in reports], threshold, linkage="centroid"
        )

        for group in groups:
            members = [by_id[i] for i in group]
            cluster = ReportCluster(
                label=members[0].title or "Untitled", summary="", size=len(members)
            )
            session.add(cluster)
            session.flush()
            for member in members:
                member.cluster_id = cluster.id

        stats = {"reports": len(reports), "clusters": len(groups)}
        job.status = "success"
        job.finished_at = datetime.now(UTC)
        job.stats = stats
        session.commit()
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


def merge_clusters(merger: ClusterMerger, session: Session | None = None) -> dict[str, int]:
    """Fill each cluster's merged summary. Singletons reuse their article summary;
    multi-article clusters are merged by the LLM."""
    own_session = session is None
    session = session or SessionLocal()
    job = JobRun(job_name="merge", status="started")
    session.add(job)
    session.flush()
    merged = singletons = errors = tokens = 0
    try:
        clusters = list(session.execute(select(ReportCluster)).scalars().all())
        for cluster in clusters:
            members = list(
                session.execute(
                    select(ArticleReport).where(ArticleReport.cluster_id == cluster.id)
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
            try:
                story = merger.merge(
                    [{"title": m.title, "summary": m.summary} for m in sample]
                )
            except Exception:  # noqa: BLE001 - keep other clusters if one merge fails
                errors += 1
                cluster.summary = " ".join(m.summary or "" for m in sample)
                continue
            usage = getattr(merger, "last_usage", None)
            if usage:
                tokens += int(usage.get("total_tokens") or 0)
            cluster.summary = story.summary or " ".join(m.summary or "" for m in members)
            cluster.label = story.label or cluster.label
            cluster.model = settings.mistral_model
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
