"""Article ingestion service — the shared core behind the webhook and NewsAPI.

For one incoming article: dedup by URL; obtain content (use the provided body,
else fetch the URL and clean it with readability); classify + summarize; and if
it is beauty-product related, store a raw_item + article_report (+ embedding).
Non-product articles are still recorded (article_report flagged not-related) so
we don't reprocess them. Reuses the existing summarizer/embedder/storage.
"""

import json
from datetime import datetime
from urllib.parse import urlparse

import trafilatura
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newspulse.collectors.base import BaseCollector, CollectedItem, content_hash
from newspulse.config import settings
from newspulse.models import ArticleReport, RawItem
from newspulse.pipeline.ingest import get_or_create_source
from newspulse.reports.embedder import Embedder
from newspulse.reports.merger import ClusterMerger
from newspulse.reports.pipeline import build_clusters, merge_clusters
from newspulse.reports.render import write_product_report
from newspulse.reports.summarizer import Summarizer
from newspulse.storage import ObjectStorage


class ArticleFetcher(BaseCollector):
    """BaseCollector used only for its polite fetch (robots + retry)."""

    min_interval = 0.5

    def collect(self) -> list[CollectedItem]:
        return []


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _content_for(payload: dict, fetcher: ArticleFetcher | None) -> tuple[str, str | None]:
    """Return (text, title). Prefer full body: provided content, else fetch + readability."""
    title = payload.get("title")
    text = (payload.get("content") or "").strip()
    if not text and fetcher is not None and payload.get("url"):
        try:
            doc = trafilatura.bare_extraction(fetcher.fetch(payload["url"]), with_metadata=True)
        except Exception:  # noqa: BLE001 - unreachable/JS/paywalled: fall back to description
            doc = None
        if doc and (doc.text or "").strip():
            text = doc.text.strip()
            title = title or getattr(doc, "title", None)
    if not text:
        text = (payload.get("description") or "").strip()
    return text, title


def ingest_article(
    payload: dict,
    *,
    session: Session,
    storage: ObjectStorage,
    summarizer: Summarizer,
    embedder: Embedder | None = None,
    fetcher: ArticleFetcher | None = None,
) -> dict:
    """Ingest one article. Returns {status, product?}."""
    url = payload.get("url")
    if not url:
        return {"status": "no_url"}
    digest = content_hash(url)
    if session.execute(select(RawItem.id).where(RawItem.content_hash == digest)).first():
        return {"status": "duplicate"}

    text, title = _content_for(payload, fetcher)
    if not text:
        return {"status": "no_content"}

    result = summarizer.summarize(title, text, [])

    source_name = payload.get("source_name") or "NewsAPI"
    root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    source = get_or_create_source(session, source_name, root, "news", None)

    stored = json.dumps(
        {"url": url, "title": title, "body": text, "source": source_name}, ensure_ascii=False
    ).encode("utf-8")
    raw_ref = storage.put(f"{digest}.json", stored)
    raw = RawItem(
        source_id=source.id, url=url, title=title, content_hash=digest,
        raw_ref=raw_ref, published_at=_parse_dt(payload.get("published_at")),
    )
    session.add(raw)
    session.flush()

    report = ArticleReport(
        raw_item_id=raw.id,
        is_product_related=result.is_product_related,
        title=result.label or title,
        summary=result.summary or None,
        products=result.products,
        model=settings.mistral_model,
    )
    if result.is_product_related and embedder is not None:
        report.embedding = embedder.embed([result.summary or result.label or title or ""])[0]
    session.add(report)
    session.commit()

    return {
        "status": "ingested" if result.is_product_related else "skipped_not_product",
        "product": result.is_product_related,
    }


def maybe_rebuild(
    session: Session,
    merger: ClusterMerger,
    threshold: int | None = None,
    storage: ObjectStorage | None = None,
) -> dict:
    """Rebuild clusters + merged report once enough new product articles accrue."""
    threshold = settings.rebuild_after_n if threshold is None else threshold
    unclustered = session.execute(
        select(func.count(ArticleReport.id)).where(
            ArticleReport.is_product_related.is_(True),
            ArticleReport.cluster_id.is_(None),
        )
    ).scalar() or 0
    if unclustered < threshold:
        return {"rebuilt": False, "unclustered": unclustered}
    build_clusters(session=session)
    merge_clusters(merger, session=session)
    if storage is not None:
        write_product_report(session=session, storage=storage)
    return {"rebuilt": True, "unclustered": unclustered}
