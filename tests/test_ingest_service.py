"""Part 9.1 — article ingestion service (offline)."""

from newspulse.feeds.service import ingest_article, maybe_rebuild
from newspulse.models import ArticleReport, RawItem, ReportCluster, Source
from newspulse.reports.embedder import FakeEmbedder
from newspulse.reports.merger import FakeMerger, MergedStory
from newspulse.reports.summarizer import ArticleSummary, FakeSummarizer


class DictStorage:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> str:
        self.data[key] = data
        return f"local://{key}"

    def get(self, key: str) -> bytes:
        return self.data[key]


class FakeFetcher:
    def __init__(self, html: str) -> None:
        self.html = html

    def fetch(self, url: str) -> str:
        return self.html


PRODUCT = ArticleSummary(
    is_product_related=True, label="Best serums", summary="A serum guide.", products=["CeraVe"]
)
NOT_PRODUCT = ArticleSummary(is_product_related=False, summary="celeb news")

ARTICLE_HTML = """<html><head><title>Serum guide</title></head><body><article>
<p>This serum roundup covers niacinamide and hyaluronic acid options for dry skin.</p>
<p>Several brands are featured with notes on texture and price for shoppers.</p>
<p>Dermatologists weigh in on what to look for in a good serum.</p>
</article></body></html>"""


def _payload(url="https://mag.example/a", **extra) -> dict:
    base = {
        "url": url, "title": "Serum guide", "source_name": "Mag",
        "published_at": "2026-08-01T00:00:00Z",
    }
    base.update(extra)
    return base


def test_ingest_product_article(db_session) -> None:
    storage = DictStorage()
    result = ingest_article(
        _payload(content="A long serum article about beauty products."),
        session=db_session, storage=storage,
        summarizer=FakeSummarizer(PRODUCT), embedder=FakeEmbedder({"A serum guide.": [1.0, 0.0]}),
    )
    assert result == {"status": "ingested", "product": True}
    rep = db_session.query(ArticleReport).one()
    assert rep.is_product_related is True
    assert rep.embedding == [1.0, 0.0]
    assert db_session.query(RawItem).count() == 1
    assert db_session.query(Source).filter_by(name="Mag").count() == 1


def test_ingest_not_product_article(db_session) -> None:
    storage = DictStorage()
    result = ingest_article(
        _payload(content="celebrity gossip"),
        session=db_session, storage=storage,
        summarizer=FakeSummarizer(NOT_PRODUCT), embedder=FakeEmbedder({}),
    )
    assert result["status"] == "skipped_not_product"
    rep = db_session.query(ArticleReport).one()
    assert rep.is_product_related is False
    assert rep.embedding is None


def test_ingest_duplicate(db_session) -> None:
    storage = DictStorage()
    args = dict(session=db_session, storage=storage, summarizer=FakeSummarizer(PRODUCT),
                embedder=FakeEmbedder({"A serum guide.": [1.0, 0.0]}))
    ingest_article(_payload(content="x"), **args)
    assert ingest_article(_payload(content="x"), **args)["status"] == "duplicate"
    assert db_session.query(RawItem).count() == 1


def test_ingest_fetches_when_no_content(db_session) -> None:
    storage = DictStorage()
    result = ingest_article(
        _payload(),  # no content -> must fetch
        session=db_session, storage=storage,
        summarizer=FakeSummarizer(PRODUCT), embedder=FakeEmbedder({"A serum guide.": [1.0, 0.0]}),
        fetcher=FakeFetcher(ARTICLE_HTML),
    )
    assert result["status"] == "ingested"


def _seed_product_report(session, storage, n) -> None:
    src = session.query(Source).filter_by(name="Src").one_or_none()
    if src is None:
        src = Source(name="Src", url="https://e", type="news")
        session.add(src)
        session.flush()
    start = session.query(RawItem).count()
    for i in range(start, start + n):
        ri = RawItem(source_id=src.id, url=f"https://e/{i}", title=f"t{i}", content_hash=f"h{i}")
        session.add(ri)
        session.flush()
        session.add(ArticleReport(
            raw_item_id=ri.id, is_product_related=True, title=f"t{i}",
            summary=f"s{i}", products=["X"], embedding=[1.0, 0.0],
        ))
    session.commit()


def test_maybe_rebuild_triggers_at_threshold(db_session) -> None:
    storage = DictStorage()
    _seed_product_report(db_session, storage, 3)
    merger = FakeMerger(MergedStory(label="M", summary="merged"))
    below = maybe_rebuild(db_session, merger, threshold=5, storage=storage)
    assert below == {"rebuilt": False, "unclustered": 3}

    _seed_product_report(db_session, storage, 2)  # now 5 unclustered
    above = maybe_rebuild(db_session, merger, threshold=5, storage=storage)
    assert above["rebuilt"] is True
    assert db_session.query(ReportCluster).count() >= 1
    assert "reports/product-latest.md" in storage.data
