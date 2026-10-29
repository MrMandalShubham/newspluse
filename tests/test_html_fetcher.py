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


def test_extract_links_ranks_article_ids_first():
    """Id-bearing article links come before id-less listing pages.

    Nav/listing links appear first in the DOM but must not crowd out real
    articles once the caller caps the list.
    """
    html = """
    <html><body>
        <a href="/skincare/news">Listing page (no id)</a>
        <a href="/cosmetics/calendar/monthly">Calendar (no id)</a>
        <a href="/feed/5219998">Real article</a>
        <a href="/makeup/news/123196">Real article</a>
    </body></html>
    """
    links = _extract_links(html, "https://example.com")
    assert links[0] == "https://example.com/feed/5219998"
    assert links[1] == "https://example.com/makeup/news/123196"
    # id-less listing pages are still returned, but after the articles
    assert "https://example.com/skincare/news" in links


def test_extract_links_preserves_query_string_ids():
    """Articles keyed off a query string are not collapsed onto one URL."""
    html = """
    <html><body>
        <a href="/news/articleView.html?idxno=20862">Article A</a>
        <a href="/news/articleView.html?idxno=20861">Article B</a>
        <a href="/news/articleView.html?utm_source=x">Tracking only</a>
    </body></html>
    """
    links = _extract_links(html, "https://example.com")
    assert "https://example.com/news/articleView.html?idxno=20862" in links
    assert "https://example.com/news/articleView.html?idxno=20861" in links
    # tracking-only query strings are dropped (no article id)
    assert not any("utm_source" in link for link in links)


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
