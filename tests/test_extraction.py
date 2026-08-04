"""Part 6.3 — extraction strategies, offline on sample HTML."""

from newspulse.sources.extraction import (
    JsonLdExtractor,
    ReadabilityExtractor,
    build_extractor,
)
from newspulse.sources.registry import SourceConfig

JSONLD_HTML = """<html><head>
<script type="application/ld+json">{"@type":"ImageObject","url":"x"}</script>
<script type="application/ld+json">
{"@type":"Article","headline":"Foo &amp; Bar","datePublished":"2026-08-04T08:16:37+05:30",
 "articleBody":"Body &quot;text&quot; here","keywords":"niacinamide, glycerin"}
</script></head><body>ignored</body></html>"""

READABILITY_HTML = """<html><head><title>Salicylic acid rising</title>
<meta property="article:published_time" content="2026-07-15T10:00:00+05:30"/>
<meta property="article:tag" content="salicylic acid"/></head>
<body><article><h1>Salicylic acid rising</h1>
<p>Salicylic acid is increasingly popular in Indian skincare this season,
according to dermatologists across the country.</p>
<p>Brands are adding it to serums, cleansers, and body washes
for its exfoliating benefits, consumers say.</p>
<p>Consumers report clearer skin and seek multi-use formulations.</p>
</article><footer>navigation footer junk links</footer></body></html>"""


def _config(method: str) -> SourceConfig:
    return SourceConfig(
        key="s", name="Site", url="https://site.example",
        discovery={"method": "sitemap"}, extraction={"method": method},
    )


def test_jsonld_extractor() -> None:
    item = JsonLdExtractor(_config("jsonld")).extract("https://site.example/a", JSONLD_HTML)
    assert item is not None
    assert item.title == "Foo & Bar"
    assert item.body == 'Body "text" here'
    assert item.keywords == ["niacinamide", "glycerin"]
    assert item.published_at is not None and item.published_at.year == 2026


def test_jsonld_extractor_returns_none_without_body() -> None:
    assert JsonLdExtractor(_config("jsonld")).extract("u", "<html>no ld</html>") is None


def test_readability_extractor() -> None:
    item = ReadabilityExtractor(_config("readability")).extract(
        "https://site.example/b", READABILITY_HTML
    )
    assert item is not None
    assert item.body and "Salicylic acid" in item.body
    assert "footer junk" not in item.body  # boilerplate stripped
    assert item.title == "Salicylic acid rising"
    assert item.published_at is not None and item.published_at.year == 2026


def test_readability_extractor_returns_none_on_empty() -> None:
    assert ReadabilityExtractor(_config("readability")).extract("u", "<html></html>") is None


def test_build_extractor_dispatch() -> None:
    assert isinstance(build_extractor(_config("jsonld")), JsonLdExtractor)
    assert isinstance(build_extractor(_config("readability")), ReadabilityExtractor)
