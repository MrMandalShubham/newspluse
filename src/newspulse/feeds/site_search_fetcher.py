"""Google News site-search fetcher — Class D scraper.

Uses our existing Google News RSS engine with ``site:`` operator to find
articles on specific domains. Each Source with scraper_class='google_news'
gets a targeted search query.

    from newspulse.feeds.site_search_fetcher import fetch_site_search_sources
    results = fetch_site_search_sources(session)
"""

from datetime import datetime

import trafilatura
from sqlalchemy import select
from sqlalchemy.orm import Session

from newspulse.db import SessionLocal
from newspulse.feeds.googlenews import GoogleNewsClient, GoogleNewsResolver
from newspulse.feeds.service import batch_ingest
from newspulse.models import Source
from newspulse.reports.embedder import MistralEmbedder
from newspulse.reports.summarizer import MistralSummarizer
from newspulse.sources.extraction import extract_image
from newspulse.storage import get_storage

DEFAULT_QUERY = "beauty OR skincare OR cosmetics"


def fetch_site_search_sources(
    session: Session | None = None,
    limit_per_source: int = 20,
) -> dict:
    """Fetch articles from all enabled google_news sources using site: queries."""
    own_session = session is None
    session = session or SessionLocal()
    storage = get_storage()
    summarizer = MistralSummarizer()
    embedder = MistralEmbedder()
    client = GoogleNewsClient()
    resolver = GoogleNewsResolver()

    sources = session.execute(
        select(Source).where(
            Source.scraper_class == "google_news",
            Source.enabled.is_(True),
        )
    ).scalars().all()

    totals: dict[str, int] = {}
    source_results: list[dict] = []

    # Phase 1 — collect payloads from all site-search sources (fast HTTP, no LLM)
    all_payloads: list[dict] = []
    for src in sources:
        src_count = 0
        try:
            domain = src.url.rstrip("/")
            if domain.startswith("http"):
                domain = domain.split("//", 1)[1]
            query_terms = src.query or DEFAULT_QUERY
            search_query = f"site:{domain} {query_terms}"

            items = client.search(search_query, limit=limit_per_source)

            for item in items:
                try:
                    final_url, html = resolver.resolve(item["gnews_url"])
                    if not html:
                        totals["unresolved"] = totals.get("unresolved", 0) + 1
                        continue

                    all_payloads.append({
                        "url": final_url,
                        "title": item["title"],
                        "content": trafilatura.extract(html),
                        "image_url": extract_image(html),
                        "source_name": item["source_name"] or src.name,
                        "published_at": (
                            item["published_at"].isoformat()
                            if item["published_at"] else None
                        ),
                        "region": src.region,
                    })
                    src_count += 1
                except Exception:
                    totals["resolve_error"] = totals.get("resolve_error", 0) + 1

            src.last_success_at = datetime.now().astimezone()
            src.last_error = None
            session.commit()
            print(
                f"[site-search] {src.name}: {len(items)} found, {src_count} resolved",
                flush=True,
            )
        except Exception as e:
            src.last_error = str(e)
            try:
                session.commit()
            except Exception:
                session.rollback()
            totals["feed_error"] = totals.get("feed_error", 0) + 1
            print(f"[site-search] {src.name}: ERROR - {e}", flush=True)

        source_results.append({"source": src.name, "resolved": src_count})

    # Phase 2+3 — concurrent LLM classification + sequential DB writes
    print(
        f"[site-search] Classifying {len(all_payloads)} articles (8 concurrent)...",
        flush=True,
    )
    batch_counts = batch_ingest(
        all_payloads, session=session, storage=storage,
        summarizer=summarizer, embedder=embedder,
    )
    for k, v in batch_counts.items():
        totals[k] = totals.get(k, 0) + v

    resolver.close()
    client.close()
    if own_session:
        session.close()

    return {"sources": len(sources), "totals": totals, "details": source_results}
