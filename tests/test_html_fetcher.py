"""Tests for the HTML crawl scraper utilities."""

from newspulse.feeds.html_fetcher import _extract_links, _parse_sitemap


def test_extract_links_filters_nav():
    html = """
    <html><body>
        <a href="/news/article-123">Good article</a>
        <a href="/category/beauty">Category</a>
        <a href="/about">About page</a>
        <a href="/news/breaking-story-456">Another article</a>
        <a href="/login">Login</a>
    </body></html>
    """
    links = _extract_links(html, "https://example.com")
    assert "https://example.com/news/article-123" in links
    assert "https://example.com/news/breaking-story-456" in links
    assert not any("/category/" in link for link in links)
    assert not any("/about" in link for link in links)
    assert not any("/login" in link for link in links)


def test_extract_links_same_domain_only():
    html = """
    <html><body>
        <a href="https://example.com/news/art-1">Internal</a>
        <a href="https://other.com/news/art-2">External</a>
    </body></html>
    """
    links = _extract_links(html, "https://example.com")
    assert "https://example.com/news/art-1" in links
    assert not any("other.com" in link for link in links)


def test_parse_sitemap_extracts_urls():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://example.com/news/article-1</loc></url>
        <url><loc>https://example.com/news/article-2</loc></url>
        <url><loc>https://example.com/</loc></url>
    </urlset>
    """
    articles, subs = _parse_sitemap(xml)
    assert len(articles) == 2
    assert "https://example.com/news/article-1" in articles
    assert "https://example.com/news/article-2" in articles


def test_parse_sitemap_index():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <sitemap><loc>https://example.com/sitemap-news.xml</loc></sitemap>
        <sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap>
    </sitemapindex>
    """
    articles, subs = _parse_sitemap(xml)
    assert len(subs) == 2
    assert len(articles) == 0


def test_parse_sitemap_invalid_xml():
    articles, subs = _parse_sitemap("not xml at all")
    assert articles == []
    assert subs == []
