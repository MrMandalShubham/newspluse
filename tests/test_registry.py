"""Part 6.1 — source registry loading, validation, and DB sync."""

import pytest
from pydantic import ValidationError

from newspulse.models import Source
from newspulse.sources.registry import SourceConfig, load_registry, sync_sources

SAMPLE = """
sources:
  - key: a
    name: Site A
    url: https://a.example
    region: IN
    trust_score: 0.6
    section_filter: "/beauty/"
    discovery: { method: sitemap, news_sitemap: /news-sitemap.xml }
    extraction: { method: jsonld }
  - key: b
    name: Site B
    url: https://b.example
    discovery: { method: rss, feeds: ["/feed.xml"] }
    extraction: { method: readability }
"""


def _write(tmp_path, text=SAMPLE):
    p = tmp_path / "sources.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_registry(tmp_path) -> None:
    cfgs = load_registry(_write(tmp_path))
    assert len(cfgs) == 2
    assert cfgs[0].name == "Site A"
    assert cfgs[0].discovery.method == "sitemap"
    assert cfgs[0].discovery.news_sitemap == "/news-sitemap.xml"
    assert cfgs[1].discovery.method == "rss"
    assert cfgs[1].discovery.feeds == ["/feed.xml"]
    # defaults applied
    assert cfgs[1].type == "news"
    assert cfgs[1].trust_score == 0.5


def test_real_registry_file_is_valid() -> None:
    cfgs = load_registry()  # config/sources.yaml
    assert any(c.name == "The Established" for c in cfgs)


def test_sync_sources_idempotent(db_session, tmp_path) -> None:
    cfgs = load_registry(_write(tmp_path))
    assert sync_sources(db_session, cfgs) == {"created": 2, "updated": 0}
    assert db_session.query(Source).count() == 2

    cfgs[0].trust_score = 0.9
    assert sync_sources(db_session, cfgs) == {"created": 0, "updated": 2}
    assert db_session.query(Source).count() == 2  # no duplicates
    assert db_session.query(Source).filter_by(name="Site A").one().trust_score == 0.9


def test_invalid_method_rejected() -> None:
    with pytest.raises(ValidationError):
        SourceConfig(
            key="x", name="X", url="u",
            discovery={"method": "bogus"},
            extraction={"method": "jsonld"},
        )
