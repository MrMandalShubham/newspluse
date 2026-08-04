"""Part 6.4 — GenericCollector composition + fleet per-source isolation."""

import httpx

from newspulse.models import RawItem, Source
from newspulse.sources.collector import GenericCollector
from newspulse.sources.registry import SourceConfig
from newspulse.sources.run import run_fleet

BASE = "https://site.example"

NEWS_SITEMAP = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://site.example/self/beauty/foo-1</loc></url>
  <url><loc>https://site.example/news/skip-2</loc></url>
</urlset>"""

ARTICLE_HTML = """<html><head>
<script type="application/ld+json">
{"@type":"Article","headline":"Foo","datePublished":"2026-08-04T08:16:37+05:30",
 "articleBody":"Niacinamide body text.","keywords":"niacinamide"}
</script></head><body>x</body></html>"""


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("/robots.txt"):
        return httpx.Response(200, text="User-agent: *\nAllow: /")
    if url.endswith("/news-sitemap.xml"):
        return httpx.Response(200, text=NEWS_SITEMAP)
    if "/self/beauty/" in url:
        return httpx.Response(200, text=ARTICLE_HTML)
    return httpx.Response(404, text="nope")


def _sitemap_config(key="s", name="Site") -> SourceConfig:
    return SourceConfig(
        key=key, name=name, url=BASE, section_filter="/self/beauty/",
        discovery={"method": "sitemap", "news_sitemap": "/news-sitemap.xml"},
        extraction={"method": "jsonld"},
    )


class DictStorage:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> str:
        self.data[key] = data
        return f"local://{key}"

    def get(self, key: str) -> bytes:
        return self.data[key]


def test_generic_collector_end_to_end() -> None:
    cfg = _sitemap_config()
    collector = GenericCollector(cfg, client=httpx.Client(transport=httpx.MockTransport(_handler)))
    collector.min_interval = 0.0
    items = collector.collect()
    assert len(items) == 1
    assert items[0].source_name == "Site"
    assert items[0].body == "Niacinamide body text."


class _FakeCollector:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail

    def discover(self) -> list[str]:
        if self.fail:
            raise RuntimeError("boom")
        return []

    def discover_backfill(self, since) -> list[str]:
        return []

    def collect_urls(self, urls) -> list:
        return []

    def close(self) -> None:
        pass


class _FakeRenderer:
    def __init__(self, html: str) -> None:
        self.html = html
        self.calls: list[str] = []

    def render(self, url: str) -> str:
        self.calls.append(url)
        return self.html

    def close(self) -> None:
        pass


def _playwright_config() -> SourceConfig:
    return SourceConfig(
        key="p", name="P", url=BASE, render="playwright", max_articles=2,
        discovery={"method": "htmlcrawl", "list_pages": ["/beauty"], "link_pattern": "/article/"},
        extraction={"method": "readability"},
    )


def test_fetch_dispatches_to_renderer_when_playwright() -> None:
    renderer = _FakeRenderer("<html>RENDERED</html>")
    col = GenericCollector(
        _playwright_config(),
        client=httpx.Client(transport=httpx.MockTransport(_handler)),
        renderer=renderer,
    )
    col.min_interval = 0.0
    assert col.fetch("https://site.example/article/x") == "<html>RENDERED</html>"
    assert renderer.calls == ["https://site.example/article/x"]


def test_fetch_uses_httpx_by_default() -> None:
    col = GenericCollector(
        _sitemap_config(), client=httpx.Client(transport=httpx.MockTransport(_handler))
    )
    col.min_interval = 0.0
    html = col.fetch("https://site.example/self/beauty/foo-1")
    assert "articleBody" in html  # static fetch, not rendered


def test_max_articles_caps_collect_urls() -> None:
    cfg = SourceConfig(
        key="c", name="C", url=BASE, section_filter="/self/beauty/", max_articles=2,
        discovery={"method": "sitemap", "news_sitemap": "/news-sitemap.xml"},
        extraction={"method": "jsonld"},
    )
    col = GenericCollector(cfg, client=httpx.Client(transport=httpx.MockTransport(_handler)))
    col.min_interval = 0.0
    urls = [f"https://site.example/self/beauty/{n}" for n in ("a", "b", "c")]
    assert len(col.collect_urls(urls)) == 2  # capped at max_articles


def test_fleet_isolates_a_failing_source(db_session) -> None:
    cfgs = [_sitemap_config("a", "Site A"), _sitemap_config("b", "Site B")]

    def factory(cfg: SourceConfig) -> _FakeCollector:
        return _FakeCollector(fail=(cfg.key == "b"))

    results = run_fleet(cfgs, db_session, storage=DictStorage(), collector_factory=factory)
    assert results["a"]["status"] == "ok"
    assert results["b"]["status"] == "failed"
    assert "boom" in results["b"]["error"]
    # both sources still synced despite one failing
    assert db_session.query(Source).count() == 2
    assert db_session.query(RawItem).count() == 0  # fakes produced no items
