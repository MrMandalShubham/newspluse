"""Part 8.2 — article classify+summarize parsing and pipeline (offline)."""

import json

from newspulse.models import ArticleReport, RawItem, Source
from newspulse.reports.pipeline import summarize_pending
from newspulse.reports.summarizer import ArticleSummary, FakeSummarizer, MistralSummarizer


class DictStorage:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> str:
        self.data[key] = data
        return f"local://{key}"

    def get(self, key: str) -> bytes:
        return self.data[key]


def _seed_item(session, storage, *, hash_="h1", title="A body wash guide") -> RawItem:
    src = session.query(Source).filter_by(name="Src").one_or_none()
    if src is None:
        src = Source(name="Src", url="https://e", type="news")
        session.add(src)
        session.flush()
    key = f"{hash_}.json"
    storage.put(key, json.dumps({"title": title, "body": "text", "keywords": []}).encode())
    item = RawItem(source_id=src.id, url=f"https://e/{hash_}", title=title,
                   content_hash=hash_, raw_ref=f"local://{key}")
    session.add(item)
    session.flush()
    return item


def test_parse_valid_and_malformed() -> None:
    good = (
        '{"is_product_related": true, "label": "Best body washes", '
        '"summary": "A guide.", "products": ["CeraVe", "salicylic acid"]}'
    )
    r = MistralSummarizer.parse(good)
    assert r.is_product_related is True
    assert r.label == "Best body washes"
    assert r.products == ["CeraVe", "salicylic acid"]
    # malformed -> safe default (not relevant)
    assert MistralSummarizer.parse("not json").is_product_related is False


def test_summarize_pending_creates_reports(db_session) -> None:
    storage = DictStorage()
    _seed_item(db_session, storage, hash_="a", title="Body wash guide")
    _seed_item(db_session, storage, hash_="b", title="Celebrity gossip")
    fake = FakeSummarizer(
        ArticleSummary(is_product_related=True, label="Body wash guide",
                       summary="Guide to body washes.", products=["CeraVe"])
    )
    stats = summarize_pending(fake, session=db_session, storage=storage)
    assert stats["processed"] == 2
    assert stats["relevant"] == 2
    assert db_session.query(ArticleReport).count() == 2
    rep = db_session.query(ArticleReport).first()
    assert rep.is_product_related is True
    assert rep.products == ["CeraVe"]


def test_summarize_pending_is_idempotent(db_session) -> None:
    storage = DictStorage()
    _seed_item(db_session, storage, hash_="a")
    fake = FakeSummarizer(ArticleSummary(is_product_related=False, summary="n/a"))
    summarize_pending(fake, session=db_session, storage=storage)
    stats = summarize_pending(fake, session=db_session, storage=storage)  # already summarized
    assert stats["processed"] == 0
    assert db_session.query(ArticleReport).count() == 1
