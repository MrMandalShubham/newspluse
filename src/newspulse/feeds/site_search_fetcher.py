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
from newspulse.feeds.service import ingest_article
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

    for src in sources:
        src_stats: dict[str, int] = {}
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
                        src_stats["unresolved"] = src_stats.get("unresolved", 0) + 1
                        totals["unresolved"] = totals.get("unresolved", 0) + 1
                        continue

                    payload = {
                        "url": final_url,
                        "title": item["title"],
                        "content": trafilatura.extract(html),
                        "image_url": extract_image(html),
                        "source_name": item["source_name"] or src.name,
                        "published_at": (
                            item["published_at"].isoformat() if item["published_at"] else None
                        ),
                        "region": src.region,
                    }
                    res = ingest_article(
                        payload, session=session, storage=storage,
                        summarizer=summarizer, embedder=embedder, fetcher=None,
                    )
                    status = res["status"]
                    src_stats[status] = src_stats.get(status, 0) + 1
                    totals[status] = totals.get(status, 0) + 1
                except Exception:
                    src_stats["error"] = src_stats.get("error", 0) + 1
                    totals["error"] = totals.get("error", 0) + 1
                    try:
                        session.rollback()
                    except Exception:
                        pass

            src.last_success_at = datetime.now().astimezone()
            src.last_error = None
            session.commit()
            print(
                f"[site-search] {src.name}: {len(items)} found | {src_stats}",
                flush=True,
            )
        except Exception as e:
            src.last_error = str(e)
            try:
                session.commit()
            except Exception:
                session.rollback()
            src_stats["feed_error"] = 1
            totals["feed_error"] = totals.get("feed_error", 0) + 1
            print(f"[site-search] {src.name}: ERROR - {e}", flush=True)

        source_results.append({"source": src.name, "stats": src_stats})

    resolver.close()
    client.close()
    if own_session:
        session.close()

    return {"sources": len(sources), "totals": totals, "details": source_results}
