"""RSS feed fetcher — Class A scraper.

Fetches articles from RSS/Atom feeds, extracts article URLs and metadata,
and feeds them into the standard ingestion pipeline.

    from newspulse.feeds.rss_fetcher import fetch_rss_sources
    results = fetch_rss_sources(session)
"""

from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx
import trafilatura
from sqlalchemy import select
from sqlalchemy.orm import Session

from newspulse.db import SessionLocal
from newspulse.feeds.service import ingest_article
from newspulse.models import Source
from newspulse.reports.embedder import MistralEmbedder
from newspulse.reports.summarizer import MistralSummarizer
from newspulse.sources.extraction import extract_image
from newspulse.storage import get_storage

ATOM_NS = "{http://www.w3.org/2005/Atom}"
RSS10_NS = "{http://purl.org/rss/1.0/}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"
_UA = "Mozilla/5.0 (compatible; NewsPulseBot/1.0)"


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _parse_feed(xml_text: str) -> list[dict]:
    """Parse RSS 2.0, Atom, or RDF/RSS 1.0 feed XML into a list of article dicts."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items: list[dict] = []

    # RSS 2.0: <rss><channel><item>
    for item in root.findall(".//item"):
        link = (item.findtext("link") or "").strip()
        if not link:
            continue
        items.append({
            "url": link,
            "title": (item.findtext("title") or "").strip(),
            "description": (item.findtext("description") or "").strip(),
            "published_at": _parse_date(item.findtext("pubDate")),
        })

    # Atom: <feed><entry>
    if not items:
        for entry in root.findall(f".//{ATOM_NS}entry"):
            link_el = entry.find(f"{ATOM_NS}link[@rel='alternate']")
            if link_el is None:
                link_el = entry.find(f"{ATOM_NS}link")
            link = (link_el.get("href", "") if link_el is not None else "").strip()
            if not link:
                continue
            items.append({
                "url": link,
                "title": (entry.findtext(f"{ATOM_NS}title") or "").strip(),
                "description": (entry.findtext(f"{ATOM_NS}summary") or "").strip(),
                "published_at": _parse_date(
                    entry.findtext(f"{ATOM_NS}published")
                    or entry.findtext(f"{ATOM_NS}updated")
                ),
            })

    # RDF / RSS 1.0: <rdf:RDF><item xmlns="http://purl.org/rss/1.0/">
    if not items:
        for item in root.findall(f".//{RSS10_NS}item"):
            link = (item.findtext(f"{RSS10_NS}link") or "").strip()
            if not link:
                continue
            items.append({
                "url": link,
                "title": (item.findtext(f"{RSS10_NS}title") or "").strip(),
                "description": (
                    item.findtext(f"{RSS10_NS}description") or ""
                ).strip(),
                "published_at": _parse_date(item.findtext(f"{DC_NS}date")),
            })

    return items


def fetch_rss(feed_url: str, client: httpx.Client | None = None) -> list[dict]:
    """Fetch and parse a single RSS/Atom feed URL."""
    _client = client or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": _UA})
    try:
        resp = _client.get(feed_url)
        resp.raise_for_status()
        return _parse_feed(resp.text)
    except Exception:
        return []
    finally:
        if client is None:
            _client.close()


def fetch_rss_sources(session: Session | None = None) -> dict:
    """Fetch articles from all enabled RSS sources and ingest them."""
    own_session = session is None
    session = session or SessionLocal()
    storage = get_storage()
    summarizer = MistralSummarizer()
    embedder = MistralEmbedder()
    client = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": _UA})

    sources = session.execute(
        select(Source).where(
            Source.scraper_class == "rss",
            Source.enabled.is_(True),
            Source.feed_url.isnot(None),
        )
    ).scalars().all()

    totals: dict[str, int] = {}
    source_results: list[dict] = []

    for src in sources:
        src_stats: dict[str, int] = {}
        try:
            feed_items = fetch_rss(src.feed_url, client=client)
            for item in feed_items:
                try:
                    url = item["url"]
                    html = None
                    try:
                        page_resp = client.get(url)
                        if page_resp.status_code == 200:
                            html = page_resp.text
                    except Exception:
                        pass

                    payload = {
                        "url": url,
                        "title": item.get("title"),
                        "content": trafilatura.extract(html) if html else None,
                        "image_url": extract_image(html) if html else None,
                        "description": item.get("description"),
                        "source_name": src.name,
                        "published_at": (
                            item["published_at"].isoformat() if item.get("published_at") else None
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
        except Exception as e:
            src.last_error = str(e)
            try:
                session.commit()
            except Exception:
                session.rollback()
            src_stats["feed_error"] = 1
            totals["feed_error"] = totals.get("feed_error", 0) + 1

        source_results.append({"source": src.name, "stats": src_stats})
        print(f"[rss] {src.name}: {src_stats}", flush=True)

    client.close()
    if own_session:
        session.close()

    return {"sources": len(sources), "totals": totals, "details": source_results}
