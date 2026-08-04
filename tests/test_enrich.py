"""Part 2.2 — extraction parsing + enrichment pipeline (offline, fake extractor)."""

import json

from newspulse.enrich.llm import ExtractionResult, FakeExtractor, Mention, MistralExtractor
from newspulse.models import Entity, RawItem, Signal, Source
from newspulse.pipeline.enrich import enrich_pending


class DictStorage:
    """Tiny in-memory ObjectStorage stand-in."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> str:
        self.data[key] = data
        return f"local://{key}"

    def get(self, key: str) -> bytes:
        return self.data[key]


def _seed_item(session, storage, *, hash_="h1", body="body text", keywords=None) -> RawItem:
    src = session.query(Source).filter_by(name="The Established").one_or_none()
    if src is None:
        src = Source(name="The Established", url="https://e", type="news")
        session.add(src)
        session.flush()
    key = f"{hash_}.json"
    storage.put(key, json.dumps({"title": "T", "body": body, "keywords": keywords or []}).encode())
    item = RawItem(
        source_id=src.id, url=f"https://e/{hash_}", title="T",
        content_hash=hash_, raw_ref=f"local://{key}",
    )
    session.add(item)
    session.flush()
    return item


# --- parsing ------------------------------------------------------------
def test_parse_valid_json() -> None:
    good = (
        '{"mentions":[{"name":"Niacinamide","type":"ingredient",'
        '"signal_type":"mention","sentiment":0.5}]}'
    )
    r = MistralExtractor.parse(good)
    assert len(r.mentions) == 1
    assert r.mentions[0].name == "Niacinamide"


def test_parse_drops_malformed_and_out_of_vocab() -> None:
    assert MistralExtractor.parse("not json").mentions == []
    bad_type = '{"mentions":[{"name":"X","type":"planet","signal_type":"mention"}]}'
    assert MistralExtractor.parse(bad_type).mentions == []


# --- pipeline -----------------------------------------------------------
def test_enrich_creates_signals_and_dedups_entities(db_session) -> None:
    storage = DictStorage()
    _seed_item(db_session, storage)
    fake = FakeExtractor(
        ExtractionResult(
            mentions=[
                Mention(name="Vitamin B3", type="ingredient", signal_type="mention", sentiment=0.3),
                Mention(name="niacinamide", type="ingredient", signal_type="review", sentiment=0.1),
            ]
        )
    )
    stats = enrich_pending(fake, session=db_session, storage=storage)
    assert stats == {"processed": 1, "signals": 2}
    assert db_session.query(Signal).count() == 2
    assert db_session.query(Entity).count() == 1  # both surface forms -> one entity


def test_enrich_is_idempotent(db_session) -> None:
    storage = DictStorage()
    _seed_item(db_session, storage)
    fake = FakeExtractor(
        ExtractionResult(
            mentions=[Mention(name="Retinol", type="ingredient", signal_type="mention")]
        )
    )
    enrich_pending(fake, session=db_session, storage=storage)
    stats = enrich_pending(fake, session=db_session, storage=storage)  # already enriched
    assert stats["processed"] == 0
    assert db_session.query(Signal).count() == 1
