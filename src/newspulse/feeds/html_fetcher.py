"""HTML article-listing scraper — Class E scraper.

Fetches a source's article listing page (or its sitemap), extracts article
links, then fetches and ingests each article through the standard pipeline.

Works for sites that have no RSS feed and are not indexed by Google News.

    from newspulse.feeds.html_fetcher import fetch_html_sources
    results = fetch_html_sources(session)
"""

import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import httpx
import trafilatura
from sqlalchemy import select
from sqlalchemy.orm import Session

from newspulse.db import SessionLocal
from newspulse.feeds.service import batch_ingest
from newspulse.models import Source
from newspulse.reports.embedder import MistralEmbedder
from newspulse.reports.summarizer import MistralSummarizer
from newspulse.sources.extraction import extract_image
from newspulse.storage import get_storage

_UA = "Mozilla/5.0 (compatible; NewsPulseBot/1.0)"
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_NAV_PATTERNS = re.compile(
    r"/(tag|category|author|page|login|signup|register|search|contact|about|privacy|terms"
    r"|sitemap|rss|feed|cart|checkout|account|profile|faq|help)(/|$)",
    re.IGNORECASE,
)


class _LinkExtractor(HTMLParser):
    """Extract href values from <a> tags."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)


def _extract_links(html: str, base_url: str) -> list[str]:
    """Extract and resolve all links from an HTML page."""
    parser = _LinkExtractor()
    try:
        parser.feed(html)
    except Exception:
        return []

    base_domain = urlparse(base_url).netloc.replace("www.", "")
    seen: set[str] = set()
    result: list[str] = []

    for href in parser.links:
        url = urljoin(base_url, href).split("#")[0].split("?")[0].rstrip("/")
        if not url.startswith("http"):
            continue
        domain = urlparse(url).netloc.replace("www.", "")
        if base_domain not in domain and domain not in base_domain:
            continue
        if url in seen or url == base_url.rstrip("/"):
            continue
        path = urlparse(url).path
        if len(path) < 5 or path.count("/") < 2:
            continue
        if _NAV_PATTERNS.search(path):
            continue
        if path.endswith((".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf")):
            continue
        seen.add(url)
        result.append(url)

    return result


def _parse_sitemap(xml_text: str) -> tuple[list[str], list[str]]:
    """Parse sitemap XML. Returns (article_urls, sub_sitemap_urls)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], []

    articles: list[str] = []
    sub_sitemaps: list[str] = []

    for sitemap in root.findall(f".//{SITEMAP_NS}sitemap"):
        loc = (sitemap.findtext(f"{SITEMAP_NS}loc") or "").strip()
        if loc:
            sub_sitemaps.append(loc)

    for url_el in root.findall(f".//{SITEMAP_NS}url"):
        loc = (url_el.findtext(f"{SITEMAP_NS}loc") or "").strip()
        if not loc:
            continue
        path = urlparse(loc).path
        if len(path) < 5 or path.count("/") < 2:
            continue
        if _NAV_PATTERNS.search(path):
            continue
        articles.append(loc)

    return articles, sub_sitemaps


def _fetch_sitemap_urls(
    base_url: str, client: httpx.Client, limit: int = 30,
) -> list[str]:
    """Try to fetch article URLs from the site's sitemap."""
    domain = urlparse(base_url).netloc
    scheme = urlparse(base_url).scheme
    root = f"{scheme}://{domain}"

    for path in ["/sitemap.xml", "/wp-sitemap.xml", "/sitemap_index.xml"]:
        try:
            resp = client.get(f"{root}{path}")
            if resp.status_code != 200:
                continue
            if "xml" not in resp.headers.get("content-type", ""):
                continue
        except Exception:
            continue

        articles, sub_sitemaps = _parse_sitemap(resp.text)
        if articles:
            return articles[:limit]

        for sub_url in sub_sitemaps[:3]:
            try:
                sub_resp = client.get(sub_url)
                if sub_resp.status_code == 200:
                    sub_articles, _ = _parse_sitemap(sub_resp.text)
                    articles.extend(sub_articles)
            except Exception:
                continue
        if articles:
            return articles[:limit]

    return []


def _get_article_urls(
    src: Source, client: httpx.Client, limit: int = 20,
) -> list[str]:
    """Get article URLs from a source — try sitemap first, then HTML scrape."""
    urls = _fetch_sitemap_urls(src.url, client, limit=limit)
    if urls:
        return urls

    try:
        resp = client.get(src.url)
        if resp.status_code == 200:
            return _extract_links(resp.text, src.url)[:limit]
    except Exception:
        pass

    return []


def fetch_html_sources(
    session: Session | None = None,
    limit_per_source: int = 20,
) -> dict:
    """Fetch articles from all enabled html_crawl sources."""
    own_session = session is None
    session = session or SessionLocal()
    storage = get_storage()
    summarizer = MistralSummarizer()
    embedder = MistralEmbedder()
    client = httpx.Client(
        timeout=30, follow_redirects=True, verify=False,
        headers={"User-Agent": _UA},
    )

    sources = session.execute(
        select(Source).where(
            Source.scraper_class == "html_crawl",
            Source.enabled.is_(True),
        )
    ).scalars().all()

    totals: dict[str, int] = {}
    source_results: list[dict] = []

    # Phase 1 — collect payloads from all HTML sources (fast HTTP, no LLM)
    all_payloads: list[dict] = []
    for src in sources:
        src_count = 0
        try:
            article_urls = _get_article_urls(src, client, limit=limit_per_source)

            for url in article_urls:
                try:
                    html = None
                    try:
                        page_resp = client.get(url)
                        if page_resp.status_code == 200:
                            html = page_resp.text
                    except Exception:
                        pass

                    if not html:
                        totals["fetch_fail"] = totals.get("fetch_fail", 0) + 1
                        continue

                    all_payloads.append({
                        "url": url,
                        "title": None,
                        "content": trafilatura.extract(html),
                        "image_url": extract_image(html),
                        "source_name": src.name,
                        "published_at": None,
                        "region": src.region,
                    })
                    src_count += 1
                except Exception:
                    totals["fetch_error"] = totals.get("fetch_error", 0) + 1

            src.last_success_at = datetime.now().astimezone()
            src.last_error = None
            session.commit()
            print(
                f"[html_crawl] {src.name}: {len(article_urls)} links, {src_count} fetched",
                flush=True,
            )
        except Exception as e:
            src.last_error = str(e)
            try:
                session.commit()
            except Exception:
                session.rollback()
            totals["crawl_error"] = totals.get("crawl_error", 0) + 1
            print(f"[html_crawl] {src.name}: ERROR - {e}", flush=True)

        source_results.append({"source": src.name, "fetched": src_count})

    # Phase 2+3 — concurrent LLM classification + sequential DB writes
    print(f"[html_crawl] Classifying {len(all_payloads)} articles (8 concurrent)...", flush=True)
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
