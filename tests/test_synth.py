"""Phase 4 — Trend Card synthesis + citation integrity (offline, fake writer)."""

from datetime import datetime

from newspulse.models import Entity, RawItem, Signal, Source, Trend, TrendCard
from newspulse.pipeline.synthesize import synthesize_cards
from newspulse.synth.cards import CardDraft, FakeCardWriter


def _fixture(session):
    src = Source(name="The Established", url="https://e", type="news")
    session.add(src)
    session.flush()
    ri = RawItem(
        source_id=src.id, url="https://e/a", title="Salicylic acid guide", content_hash="c1"
    )
    session.add(ri)
    session.flush()
    ent = Entity(type="ingredient", canonical_name="salicylic acid")
    session.add(ent)
    session.flush()
    session.add(Signal(raw_item_id=ri.id, entity_id=ent.id, signal_type="mention"))
    trend = Trend(
        entity_id=ent.id, window="30d", mention_count=4, velocity=4,
        momentum_score=13.5, rank=1, computed_at=datetime(2026, 8, 4),
    )
    session.add(trend)
    session.flush()
    return ri, ent, trend


def _writer():
    return FakeCardWriter(
        CardDraft(title="Salicylic acid is surging", body="Because reasons.", so_what="Stock it.")
    )


def test_synthesis_creates_card_with_real_citations(db_session) -> None:
    ri, ent, trend = _fixture(db_session)
    stats = synthesize_cards(_writer(), session=db_session, window="30d", top_n=10)
    assert stats["created"] == 1 and stats["errors"] == 0

    card = db_session.query(TrendCard).one()
    assert card.trend_id == trend.id
    assert card.title == "Salicylic acid is surging"
    assert card.so_what == "Stock it."
    # Citation integrity: every citation points at a real raw_item that actually
    # has a signal for this trend's entity.
    assert card.citations == [{"raw_item_id": ri.id, "url": ri.url, "title": ri.title}]
    for cite in card.citations:
        sig = (
            db_session.query(Signal)
            .filter_by(raw_item_id=cite["raw_item_id"], entity_id=ent.id)
            .first()
        )
        assert sig is not None  # no orphan citations


def test_synthesis_is_idempotent(db_session) -> None:
    _fixture(db_session)
    synthesize_cards(_writer(), session=db_session, window="30d", top_n=10)
    stats = synthesize_cards(_writer(), session=db_session, window="30d", top_n=10)
    assert stats["created"] == 0 and stats["skipped"] == 1
    assert db_session.query(TrendCard).count() == 1
