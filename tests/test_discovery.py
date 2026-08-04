"""Part 6.2 — discovery strategies, offline via MockTransport."""

from datetime import date

import httpx

from newspulse.collectors.base import BaseCollector, CollectedItem
from newspulse.sources.discovery import (
    HtmlCrawlDiscovery,
    RssDiscovery,
    SitemapDiscovery,
    build_discovery,
)
from newspulse.sources.registry import SourceConfig

BASE = "https://site.example"

NEWS_SITEMAP = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://site.example/self/beauty/foo-1</loc></url>
  <url><loc>https://site.example/news/politics-2</loc></url>
</urlset>"""

INDEX_SITEMAP = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://site.example/sitemap_2026-08-03.xml</loc></sitemap>
  <sitemap><loc>https://site.example/sitemap_2020-01-01.xml</loc></sitemap>
</sitemapindex>"""

CHILD_SITEMAP = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://site.example/self/beauty/bar-3</loc></url>
  <url><loc>https://site.example/food/skip-4</loc></url>
</urlset>"""

RSS_FEED = """<rss version="2.0"><channel>
  <item><link>https://site.example/self/beauty/rss-1</link></item>
  <item><link>https://site.example/tech/rss-2</link></item>
</channel></rss>"""

LIST_PAGE = """<html><body>
  <a href="/self/beauty/crawl-1">one</a>
  <a href="https://site.example/self/beauty/crawl-2">two</a>
  <a href="/about">nope</a>
</body></html>"""


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("/robots.txt"):
        return httpx.Response(200, text="User-agent: *\nAllow: /")
    if url.endswith("/news-sitemap.xml"):
        return httpx.Response(200, text=NEWS_SITEMAP)
    if url.endswith("/webcontent-sitemap.xml"):
        return httpx.Response(200, text=INDEX_SITEMAP)
    if url.endswith("/sitemap_2026-08-03.xml"):
        return httpx.Response(200, text=CHILD_SITEMAP)
    if url.endswith("/feed.xml"):
        return httpx.Response(200, text=RSS_FEED)
    if url.endswith("/beauty-list"):
        return httpx.Response(200, text=LIST_PAGE)
    return httpx.Response(404, text="nope")


class _Collector(BaseCollector):
    min_interval = 0.0

    def collect(self) -> list[CollectedItem]:
        return []


def _collector() -> _Collector:
    return _Collector(client=httpx.Client(transport=httpx.MockTransport(_handler)))


def _config(**discovery) -> SourceConfig:
    return SourceConfig(
        key="s", name="Site", url=BASE, section_filter="/self/beauty/",
        discovery=discovery, extraction={"method": "jsonld"},
    )


def test_sitemap_discovery_filters_section() -> None:
    cfg = _config(method="sitemap", news_sitemap="/news-sitemap.xml")
    disco = build_discovery(cfg, _collector())
    assert disco.discover() == ["https://site.example/self/beauty/foo-1"]


def test_sitemap_backfill_by_date() -> None:
    cfg = _config(
        method="sitemap", news_sitemap="/news-sitemap.xml",
        index_sitemap="/webcontent-sitemap.xml",
    )
    disco = SitemapDiscovery(cfg, _collector())
    urls = disco.discover_backfill(since=date(2026, 8, 1))  # excludes 2020 child
    assert urls == ["https://site.example/self/beauty/bar-3"]


def test_rss_discovery_filters_section() -> None:
    cfg = _config(method="rss", feeds=["/feed.xml"])
    disco = RssDiscovery(cfg, _collector())
    assert disco.discover() == ["https://site.example/self/beauty/rss-1"]


def test_htmlcrawl_discovery_resolves_and_filters() -> None:
    cfg = _config(method="htmlcrawl", list_pages=["/beauty-list"])
    disco = HtmlCrawlDiscovery(cfg, _collector())
    assert disco.discover() == [
        "https://site.example/self/beauty/crawl-1",
        "https://site.example/self/beauty/crawl-2",
    ]
