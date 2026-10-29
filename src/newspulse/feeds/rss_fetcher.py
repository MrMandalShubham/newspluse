"""RSS feed fetcher — Class A scraper.

Fetches articles from RSS/Atom feeds, extracts article URLs and metadata,
and feeds them into the standard ingestion pipeline.

    from newspulse.feeds.rss_fetcher import fetch_rss_sources
    results = fetch_rss_sources(session)
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
import trafilatura
from sqlalchemy import select
from sqlalchemy.orm import Session

from newspulse.collectors.base import content_hash, safe_decode
from newspulse.db import SessionLocal
from newspulse.feeds.service import batch_ingest, known_urls
from newspulse.models import Source
from newspulse.reports.embedder import MistralEmbedder
from newspulse.reports.summarizer import MistralSummarizer
from newspulse.sources.extraction import extract_image
from newspulse.storage import get_storage

ATOM_NS = "{http://www.w3.org/2005/Atom}"
RSS10_NS = "{http://purl.org/rss/1.0/}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"
_UA = "Mozilla/5.0 (compatible; NewsPulseBot/1.0)"
_ETAG_CACHE = Path.home() / ".newspulse_etags.json"
_FETCH_WORKERS = 10


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


def _parse_feed(xml_data: str | bytes) -> list[dict]:
    """Parse RSS 2.0, Atom, or RDF/RSS 1.0 feed XML into a list of article dicts.

    Accepts bytes (preferred — lets ElementTree honour the XML encoding
    declaration, which is critical for EUC-KR / Shift_JIS / GB2312 feeds).
    """
    try:
        root = ET.fromstring(xml_data)
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


def _load_etags() -> dict[str, str]:
    try:
        return json.loads(_ETAG_CACHE.read_text())
    except Exception:
        return {}


def _save_etags(etags: dict[str, str]) -> None:
    try:
        _ETAG_CACHE.write_text(json.dumps(etags))
    except Exception:
        pass


def fetch_rss(
    feed_url: str,
    client: httpx.Client | None = None,
    etags: dict[str, str] | None = None,
) -> tuple[list[dict], bool]:
    """Fetch and parse a single RSS/Atom feed URL.

    Returns (items, changed). When the server returns 304 Not Modified,
    items is empty and changed is False — the feed hasn't updated.
    """
    _client = client or httpx.Client(
        timeout=30, follow_redirects=True, headers={"User-Agent": _UA},
    )
    try:
        headers: dict[str, str] = {}
        if etags and feed_url in etags:
            headers["If-None-Match"] = etags[feed_url]

        resp = _client.get(feed_url, headers=headers)

        if resp.status_code == 304:
            return [], False

        resp.raise_for_status()

        if etags is not None:
            etag = resp.headers.get("etag")
            if etag:
                etags[feed_url] = etag

        return _parse_feed(resp.content), True
    except Exception:
        return [], True
    finally:
        if client is None:
            _client.close()


def _fetch_page(url: str, client: httpx.Client) -> tuple[str, str | None]:
    """Fetch a single article page. Returns (url, html_or_none)."""
    try:
        resp = client.get(url)
        if resp.status_code == 200:
            return url, safe_decode(resp)
    except Exception:
        pass
    return url, None


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

    # Load ETag cache for conditional requests
    etags = _load_etags()

    # Pre-load known URL hashes for fast dedup before fetching pages
    existing_hashes = known_urls(session)

    # Phase 1a — collect article URLs from all feeds
    url_items: list[tuple[str, dict, Source]] = []
    for src in sources:
        try:
            feed_items, changed = fetch_rss(src.feed_url, client=client, etags=etags)
            if not changed:
                totals["feeds_unchanged"] = totals.get("feeds_unchanged", 0) + 1
                source_results.append({"source": src.name, "items": 0, "cached": True})
                print(f"[rss] {src.name}: unchanged (ETag)", flush=True)
                continue

            new_count = 0
            for item in feed_items:
                url = item["url"]
                if content_hash(url) in existing_hashes:
                    totals["pre_dedup"] = totals.get("pre_dedup", 0) + 1
                    continue
                url_items.append((url, item, src))
                new_count += 1

            src.last_success_at = datetime.now().astimezone()
            src.last_error = None
            session.commit()
            source_results.append({"source": src.name, "items": new_count})
            print(f"[rss] {src.name}: {new_count} new / {len(feed_items)} total", flush=True)
        except Exception as e:
            src.last_error = str(e)
            try:
                session.commit()
            except Exception:
                session.rollback()
            totals["feed_error"] = totals.get("feed_error", 0) + 1

    _save_etags(etags)

    # Phase 1b — concurrent HTTP page fetching (skip already-known URLs)
    all_payloads: list[dict] = []
    if url_items:
        print(f"[rss] Fetching {len(url_items)} pages ({_FETCH_WORKERS} concurrent)...", flush=True)
        with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
            fetch_futures = {
                pool.submit(_fetch_page, url, client): (url, item, src)
                for url, item, src in url_items
            }
            for future in as_completed(fetch_futures):
                url, item, src = fetch_futures[future]
                try:
                    _, html = future.result()
                    all_payloads.append({
                        "url": url,
                        "title": item.get("title"),
                        "content": trafilatura.extract(html) if html else None,
                        "image_url": extract_image(html) if html else None,
                        "description": item.get("description"),
                        "source_name": src.name,
                        "published_at": (
                            item["published_at"].isoformat()
                            if item.get("published_at") else None
                        ),
                        "region": src.region,
                    })
                except Exception:
                    totals["fetch_error"] = totals.get("fetch_error", 0) + 1

    # Phase 2+3+4 — concurrent LLM + sequential DB + batch embeddings
    if all_payloads:
        print(f"[rss] Classifying {len(all_payloads)} articles (8 concurrent)...", flush=True)
        batch_counts = batch_ingest(
            all_payloads, session=session, storage=storage,
            summarizer=summarizer, embedder=embedder,
        )
        for k, v in batch_counts.items():
            totals[k] = totals.get(k, 0) + v

    client.close()
    if own_session:
        session.close()

    return {"sources": len(sources), "totals": totals, "details": source_results}
