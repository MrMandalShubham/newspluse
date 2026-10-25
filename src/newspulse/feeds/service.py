"""Article ingestion service — the shared core behind the webhook and NewsAPI.

For one incoming article: dedup by URL; obtain content (use the provided body,
else fetch the URL and clean it with readability); classify + summarize; and if
it is beauty-product related, store a raw_item + article_report (+ embedding).
Non-product articles are still recorded (article_report flagged not-related) so
we don't reprocess them. Reuses the existing summarizer/embedder/storage.
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from newspulse.reports.summarizer import ArticleSummary, Summarizer
from newspulse.sources.extraction import extract_image
from newspulse.storage import ObjectStorage

MAX_WORKERS = 8
EMBED_BATCH_SIZE = 16


class _RateLimiter:
    """Token-bucket rate limiter for Mistral API (thread-safe)."""

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


_rate_limiter = _RateLimiter(calls_per_second=5.0)


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


def _content_for(
    payload: dict, fetcher: ArticleFetcher | None
) -> tuple[str, str | None, str | None]:
    """Return (text, title, image_url). Prefer full body: provided content, else fetch."""
    title = payload.get("title")
    image = payload.get("image_url")
    text = (payload.get("content") or "").strip()
    if not text and fetcher is not None and payload.get("url"):
        try:
            html = fetcher.fetch(payload["url"])
        except Exception:  # noqa: BLE001 - unreachable/JS/paywalled
            html = None
        if html:
            image = image or extract_image(html)
            try:
                doc = trafilatura.bare_extraction(html, with_metadata=True)
            except Exception:  # noqa: BLE001
                doc = None
            if doc and (doc.text or "").strip():
                text = doc.text.strip()
                title = title or getattr(doc, "title", None)
                image = image or getattr(doc, "image", None)
    if not text:
        text = (payload.get("description") or "").strip()
    return text, title, image


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

    text, title, image = _content_for(payload, fetcher)
    if not text:
        return {"status": "no_content"}

    result = summarizer.summarize(title, text, [])

    source_name = payload.get("source_name") or "NewsAPI"
    root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    source = get_or_create_source(session, source_name, root, "news", payload.get("region"))

    stored = json.dumps(
        {"url": url, "title": title, "body": text, "source": source_name, "image_url": image},
        ensure_ascii=False,
    ).encode("utf-8")
    raw_ref = storage.put(f"{digest}.json", stored)
    raw = RawItem(
        source_id=source.id, url=url, title=title, content_hash=digest,
        raw_ref=raw_ref, image_url=image, published_at=_parse_dt(payload.get("published_at")),
    )
    session.add(raw)
    session.flush()

    report = ArticleReport(
        raw_item_id=raw.id,
        is_product_related=result.is_product_related,
        title=result.label or title,
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
    if result.is_product_related and embedder is not None:
        report.embedding = embedder.embed([result.summary or result.label or title or ""])[0]
    session.add(report)
    session.commit()

    return {
        "status": "ingested" if result.is_product_related else "skipped_not_product",
        "product": result.is_product_related,
    }


def _classify_one(
    payload: dict,
    summarizer: Summarizer,
    fetcher: ArticleFetcher | None,
) -> tuple[dict, ArticleSummary | None]:
    """Classify a single article (thread-safe, no DB access)."""
    url = payload.get("url")
    if not url:
        return payload, None
    text, title, image = _content_for(payload, fetcher)
    if not text:
        return payload, None
    payload = {**payload, "_title": title, "_image": image, "_text": text}
    _rate_limiter.acquire()
    result = summarizer.summarize(title, text, [])
    return payload, result


def known_urls(session: Session) -> set[str]:
    """Return the set of URL content-hashes already in the DB (for pre-dedup)."""
    rows = session.execute(select(RawItem.content_hash)).all()
    return {r[0] for r in rows}


def batch_ingest(
    payloads: list[dict],
    *,
    session: Session,
    storage: ObjectStorage,
    summarizer: Summarizer,
    embedder: Embedder | None = None,
    fetcher: ArticleFetcher | None = None,
    max_workers: int = MAX_WORKERS,
) -> dict[str, int]:
    """Ingest articles with concurrent LLM classification.

    Phase 1: dedup by URL (fast, sequential DB check).
    Phase 2: classify concurrently via thread pool (no DB).
    Phase 3: store results sequentially (DB writes) + batch embeddings.
    """
    counts: dict[str, int] = {}

    # Phase 1 — dedup (load all known hashes once, not per-URL)
    existing = known_urls(session)
    new_payloads: list[dict] = []
    for p in payloads:
        url = p.get("url")
        if not url:
            counts["no_url"] = counts.get("no_url", 0) + 1
            continue
        digest = content_hash(url)
        if digest in existing:
            counts["duplicate"] = counts.get("duplicate", 0) + 1
            continue
        existing.add(digest)
        new_payloads.append(p)

    if not new_payloads:
        return counts

    print(
        f"  [batch] {len(new_payloads)} new / {counts.get('duplicate', 0)} dup",
        flush=True,
    )

    # Phase 2 — concurrent LLM classification (rate-limited)
    classified: list[tuple[dict, ArticleSummary | None]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_classify_one, p, summarizer, fetcher): p
            for p in new_payloads
        }
        for future in as_completed(futures):
            try:
                payload, result = future.result()
                classified.append((payload, result))
            except Exception:
                counts["error"] = counts.get("error", 0) + 1

    # Phase 3 — sequential DB writes
    embed_queue: list[tuple[ArticleReport, str]] = []
    for payload, result in classified:
        url = payload["url"]
        if result is None:
            counts["no_content"] = counts.get("no_content", 0) + 1
            continue
        try:
            digest = content_hash(url)
            if session.execute(
                select(RawItem.id).where(RawItem.content_hash == digest)
            ).first():
                counts["duplicate"] = counts.get("duplicate", 0) + 1
                continue

            title = payload.get("_title") or payload.get("title")
            image = payload.get("_image") or payload.get("image_url")
            text = payload.get("_text") or payload.get("content", "")
            source_name = payload.get("source_name") or "NewsAPI"
            root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            source = get_or_create_source(
                session, source_name, root, "news", payload.get("region"),
            )

            stored = json.dumps(
                {"url": url, "title": title, "body": text,
                 "source": source_name, "image_url": image},
                ensure_ascii=False,
            ).encode("utf-8")
            raw_ref = storage.put(f"{digest}.json", stored)
            raw = RawItem(
                source_id=source.id, url=url, title=title,
                content_hash=digest, raw_ref=raw_ref, image_url=image,
                published_at=_parse_dt(payload.get("published_at")),
            )
            session.add(raw)
            session.flush()

            report = ArticleReport(
                raw_item_id=raw.id,
                is_product_related=result.is_product_related,
                title=result.label or title,
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
            session.add(report)
            session.flush()

            if result.is_product_related and embedder is not None:
                embed_text = result.summary or result.label or title or ""
                embed_queue.append((report, embed_text))

            status = "ingested" if result.is_product_related else "skipped_not_product"
            counts[status] = counts.get(status, 0) + 1
        except Exception:
            counts["error"] = counts.get("error", 0) + 1
            try:
                session.rollback()
            except Exception:
                pass

    # Phase 4 — batch embeddings (16 at a time instead of 1-by-1)
    if embed_queue and embedder is not None:
        for i in range(0, len(embed_queue), EMBED_BATCH_SIZE):
            batch = embed_queue[i:i + EMBED_BATCH_SIZE]
            texts = [text for _, text in batch]
            try:
                vectors = embedder.embed(texts)
                for (report, _), vec in zip(batch, vectors, strict=True):
                    report.embedding = vec
            except Exception:
                pass

    session.commit()
    return counts


def ingest_article_raw(
    payload: dict,
    *,
    session: Session,
    storage: ObjectStorage,
    fetcher: ArticleFetcher | None = None,
) -> dict:
    """Store one article WITHOUT LLM enrichment (link + image + title + body only).

    Used when no LLM is available: captures the raw material now so it can be
    enriched later by ``backfill_enrich``. Creates a RawItem but no ArticleReport.
    """
    url = payload.get("url")
    if not url:
        return {"status": "no_url"}
    digest = content_hash(url)
    if session.execute(select(RawItem.id).where(RawItem.content_hash == digest)).first():
        return {"status": "duplicate"}

    text, title, image = _content_for(payload, fetcher)
    if not text:
        return {"status": "no_content"}

    source_name = payload.get("source_name") or "NewsAPI"
    root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    source = get_or_create_source(session, source_name, root, "news", payload.get("region"))

    stored = json.dumps(
        {"url": url, "title": title, "body": text, "source": source_name, "image_url": image},
        ensure_ascii=False,
    ).encode("utf-8")
    raw_ref = storage.put(f"{digest}.json", stored)
    raw = RawItem(
        source_id=source.id, url=url, title=title, content_hash=digest,
        raw_ref=raw_ref, image_url=image, published_at=_parse_dt(payload.get("published_at")),
    )
    session.add(raw)
    session.commit()
    return {"status": "raw_stored"}


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
