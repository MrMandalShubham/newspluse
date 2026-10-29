"""Tests for the RSS feed parser."""

from newspulse.feeds.rss_fetcher import _parse_feed

RSS_SAMPLE = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Test Feed</title>
  <item>
    <title>Shiseido Launches New Serum</title>
    <link>https://example.com/article/1</link>
    <description>Shiseido announced a new serum today.</description>
    <pubDate>Wed, 09 Oct 2026 10:00:00 GMT</pubDate>
  </item>
  <item>
    <title>K-Beauty Trends 2026</title>
    <link>https://example.com/article/2</link>
    <description>Korean beauty trends are evolving.</description>
    <pubDate>Tue, 08 Oct 2026 08:00:00 GMT</pubDate>
  </item>
  <item>
    <title>No Link Item</title>
    <description>This item has no link and should be skipped.</description>
  </item>
</channel>
</rss>"""

ATOM_SAMPLE = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>Cosmax Expands to Thailand</title>
    <link rel="alternate" href="https://example.com/atom/1"/>
    <summary>Cosmax opens new facility.</summary>
    <published>2026-10-09T10:00:00Z</published>
  </entry>
</feed>"""


def test_parse_rss_feed():
    items = _parse_feed(RSS_SAMPLE)
    assert len(items) == 2
    assert items[0]["title"] == "Shiseido Launches New Serum"
    assert items[0]["url"] == "https://example.com/article/1"
    assert items[0]["published_at"] is not None
    assert items[1]["title"] == "K-Beauty Trends 2026"


def test_parse_atom_feed():
    items = _parse_feed(ATOM_SAMPLE)
    assert len(items) == 1
    assert items[0]["title"] == "Cosmax Expands to Thailand"
    assert items[0]["url"] == "https://example.com/atom/1"
    assert items[0]["published_at"] is not None


def test_parse_invalid_xml():
    items = _parse_feed("not xml at all")
    assert items == []


def test_parse_empty_feed():
    items = _parse_feed('<?xml version="1.0"?><rss><channel></channel></rss>')
    assert items == []


def test_parse_malformed_feed_recovers():
    """A UTF-8-declared feed containing a stray CP1252 byte (0xA0) still parses.

    ElementTree rejects the whole document; the lenient fallback salvages the
    items. Regression for dailyvanity.sg, which embedded a raw 0xA0 in article
    HTML and silently yielded zero articles.
    """
    feed = (
        b'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        b'<item><title>Ceramide\xa0Cream</title>'
        b'<link>https://example.com/news/1</link>'
        b'<description>Dry\xa0itchy skin</description></item>'
        b'<item><title>Second</title><link>https://example.com/news/2</link></item>'
        b'</channel></rss>'
    )
    items = _parse_feed(feed)
    assert len(items) == 2
    assert items[0]["url"] == "https://example.com/news/1"
    assert items[1]["url"] == "https://example.com/news/2"
