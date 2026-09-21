"""Backfill / refresh LLM enrichment for stored articles.

Two modes:
  * default  — enrich only raw items with NO ArticleReport (e.g. those ingested
               via ``--raw`` while no LLM was available).
  * --refresh — re-run enrichment on EVERY raw item and UPDATE existing reports
               (used to roll out prompt/schema changes across the back catalog).

Both then re-embed, re-cluster, re-merge and write the product report.

    python -m newspulse.feeds.backfill_enrich [--limit N] [--refresh] [--no-rebuild]
"""

import argparse
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from newspulse.config import settings
from newspulse.db import SessionLocal
from newspulse.models import ArticleReport, RawItem
from newspulse.reports.embedder import MistralEmbedder
from newspulse.reports.merger import MistralMerger
from newspulse.reports.pipeline import build_clusters, merge_clusters
from newspulse.reports.summarizer import ArticleSummary, MistralSummarizer
from newspulse.storage import ObjectStorage, get_storage


def _targets(session: Session, refresh: bool, limit: int | None) -> list[RawItem]:
    stmt = select(RawItem).order_by(RawItem.id)
    if not refresh:
        stmt = stmt.outerjoin(
            ArticleReport, ArticleReport.raw_item_id == RawItem.id
        ).where(ArticleReport.id.is_(None))
    if limit:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars())


def _body_for(storage: ObjectStorage, raw: RawItem) -> str:
    try:
        blob = storage.get(f"{raw.content_hash}.json")
        return (json.loads(blob).get("body") or "").strip()
    except Exception:  # noqa: BLE001 - missing/corrupt blob -> nothing to enrich
        return ""


def _apply(report: ArticleReport, raw: RawItem, result: ArticleSummary) -> None:
    """Write summarizer output onto a (new or existing) report."""
    report.is_product_related = result.is_product_related
    report.title = result.label or raw.title
    report.summary = result.summary or None
    report.category = result.category or None
    report.sentiment = result.sentiment or None
    report.theme = result.theme or None
    report.event_types = result.event_types
    report.importance_score = result.importance_score or None
    report.country = result.country or None
    report.brands = result.brands
    report.companies = result.companies
    report.ingredients = result.ingredients
    report.products = result.products
    report.model = settings.mistral_model


def backfill_enrich(
    limit: int | None = None, refresh: bool = False, rebuild: bool = True
) -> dict:
    session = SessionLocal()
    storage = get_storage()
    summarizer = MistralSummarizer()
    embedder = MistralEmbedder()
    counts = {"enriched": 0, "product": 0, "no_body": 0}
    try:
        targets = _targets(session, refresh, limit)
        for raw in targets:
            body = _body_for(storage, raw)
            if not body:
                counts["no_body"] += 1
                continue
            result = summarizer.summarize(raw.title, body, [])
            report = session.execute(
                select(ArticleReport).where(ArticleReport.raw_item_id == raw.id)
            ).scalar_one_or_none()
            if report is None:
                report = ArticleReport(raw_item_id=raw.id)
                session.add(report)
            _apply(report, raw, result)
            # Summary changed -> recompute the embedding inline with a real vector.
            if result.is_product_related:
                report.embedding = embedder.embed(
                    [result.summary or result.label or raw.title or ""]
                )[0]
                counts["product"] += 1
            session.commit()
            counts["enriched"] += 1

        rebuild_stats = None
        if rebuild:
            clustered = build_clusters(session=session)
            merged = merge_clusters(MistralMerger(), session=session)
            rebuild_stats = {"cluster": clustered, "merge": merged}
        return {"targets": len(targets), "counts": counts, "rebuild": rebuild_stats}
    finally:
        session.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backfill / refresh LLM enrichment.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--refresh", action="store_true", help="Re-enrich existing reports too.")
    parser.add_argument("--no-rebuild", action="store_true")
    args = parser.parse_args(argv)
    print(
        f"[backfill] "
        f"{backfill_enrich(limit=args.limit, refresh=args.refresh, rebuild=not args.no_rebuild)}"
    )


if __name__ == "__main__":
    main()
