"""Google News RSS parsing (offline). Link resolution uses Playwright (live)."""

import httpx

from newspulse.feeds.googlenews import GoogleNewsClient

RSS = """<rss version="2.0"><channel><title>Google News</title>
<item>
  <title>From Snail Mucin to PDRN, Ingredients That Define K-beauty - Vogue</title>
  <link>https://news.google.com/rss/articles/ABC123?oc=5</link>
  <pubDate>Mon, 04 Aug 2026 09:00:00 GMT</pubDate>
  <source url="https://www.vogue.com">Vogue</source>
</item>
<item>
  <title>No link item - Nowhere</title>
  <pubDate>Mon, 04 Aug 2026 09:00:00 GMT</pubDate>
</item>
</channel></rss>"""


def _handler(request: httpx.Request) -> httpx.Response:
    assert "news.google.com/rss/search" in str(request.url)
    return httpx.Response(200, text=RSS)


def test_search_parses_and_cleans_titles() -> None:
    transport = httpx.MockTransport(_handler)
    client = GoogleNewsClient(client=httpx.Client(transport=transport))
    items = client.search("k-beauty", limit=10)
    assert len(items) == 1  # the link-less item is dropped
    item = items[0]
    # source suffix stripped from the title
    assert item["title"] == "From Snail Mucin to PDRN, Ingredients That Define K-beauty"
    assert item["source_name"] == "Vogue"
    assert item["gnews_url"].endswith("ABC123?oc=5")
    assert item["published_at"] is not None and item["published_at"].year == 2026
