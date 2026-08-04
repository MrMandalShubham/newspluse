"""Part 1.2 — The Established collector parsing, offline via MockTransport."""

from datetime import date

import httpx

from newspulse.collectors.theestablished import EstablishedCollector

ROBOTS_ALLOW = "User-agent: *\nAllow: /"

NEWS_SITEMAP = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.theestablished.com/self/beauty/foo-1</loc></url>
  <url><loc>https://www.theestablished.com/web-stories/bar-2</loc></url>
</urlset>"""

INDEX_SITEMAP = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.theestablished.com/sitemap_2026-08-03.xml</loc></sitemap>
  <sitemap><loc>https://www.theestablished.com/sitemap_2020-01-01.xml</loc></sitemap>
</sitemapindex>"""

CHILD_SITEMAP = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.theestablished.com/self/beauty/cosmetic-1</loc></url>
  <url><loc>https://www.theestablished.com/web-stories/skip-me</loc></url>
</urlset>"""

ARTICLE_HTML = """<html><head>
<script type="application/ld+json">{"@type":"ImageObject","url":"x"}</script>
<script type="application/ld+json">
{"@type":"Article","headline":"Foo &amp; Bar","datePublished":"2026-08-04T08:16:37+05:30",
 "articleBody":"Body &quot;text&quot; here","keywords":"niacinamide, glycerin"}
</script>
</head><body>ignored</body></html>"""


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("/robots.txt"):
        return httpx.Response(200, text=ROBOTS_ALLOW)
    if url.endswith("/news-sitemap.xml"):
        return httpx.Response(200, text=NEWS_SITEMAP)
    if url.endswith("/webcontent-sitemap.xml"):
        return httpx.Response(200, text=INDEX_SITEMAP)
    if url.endswith("/sitemap_2026-08-03.xml"):
        return httpx.Response(200, text=CHILD_SITEMAP)
    if "/self/beauty/" in url:
        return httpx.Response(200, text=ARTICLE_HTML)
    return httpx.Response(404, text="nope")


def _collector() -> EstablishedCollector:
    client = httpx.Client(transport=httpx.MockTransport(_handler))
    c = EstablishedCollector(client=client)
    c.min_interval = 0.0
    return c


def test_discover_news_keeps_only_beauty() -> None:
    urls = _collector().discover_news()
    assert urls == ["https://www.theestablished.com/self/beauty/foo-1"]


def test_parse_article_extracts_from_jsonld() -> None:
    c = _collector()
    item = c.parse_article("https://www.theestablished.com/self/beauty/foo-1", ARTICLE_HTML)
    assert item is not None
    assert item.title == "Foo & Bar"
    assert item.body == 'Body "text" here'
    assert item.keywords == ["niacinamide", "glycerin"]
    assert item.lang == "en"
    assert item.published_at is not None
    assert item.published_at.year == 2026 and item.published_at.tzinfo is not None


def test_collect_urls_end_to_end() -> None:
    c = _collector()
    items = c.collect_urls(["https://www.theestablished.com/self/beauty/foo-1"])
    assert len(items) == 1
    assert items[0].source_name == "The Established"
    assert items[0].body


def test_backfill_respects_date_window() -> None:
    c = _collector()
    urls = c.discover_backfill(since=date(2026, 8, 1))  # excludes the 2020 child
    assert urls == ["https://www.theestablished.com/self/beauty/cosmetic-1"]
