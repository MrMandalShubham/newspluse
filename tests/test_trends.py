"""Phase 3 — deterministic momentum scoring on a synthetic dataset."""

from datetime import datetime, timedelta

from newspulse.models import Entity, RawItem, Signal, Source
from newspulse.pipeline.trends import compute_all, compute_trends


def _fixture(session):
    s1 = Source(name="S1", url="u1", type="news")
    s2 = Source(name="S2", url="u2", type="news")
    session.add_all([s1, s2])
    session.flush()
    ri1 = RawItem(source_id=s1.id, url="a", content_hash="c1")
    ri2 = RawItem(source_id=s2.id, url="b", content_hash="c2")
    session.add_all([ri1, ri2])
    session.flush()
    a = Entity(type="ingredient", canonical_name="retinol")
    b = Entity(type="ingredient", canonical_name="glycerin")
    session.add_all([a, b])
    session.flush()
    return ri1, ri2, a, b


def _sig(session, ri, ent, when, sentiment):
    session.add(
        Signal(
            raw_item_id=ri.id,
            entity_id=ent.id,
            signal_type="mention",
            sentiment=sentiment,
            observed_at=when,
        )
    )


def test_momentum_ranking_and_scores(db_session) -> None:
    now = datetime(2026, 8, 4)  # naive UTC for SQLite
    ri1, ri2, a, b = _fixture(db_session)
    cur = now - timedelta(days=5)   # inside current 30d window
    prev = now - timedelta(days=45)  # inside prior 30d window

    # Entity A: rising — 4 current across 2 sources (sent 0.5), 1 prior -> velocity 3
    _sig(db_session, ri1, a, cur, 0.5)
    _sig(db_session, ri1, a, cur, 0.5)
    _sig(db_session, ri2, a, cur, 0.5)
    _sig(db_session, ri2, a, cur, 0.5)
    _sig(db_session, ri1, a, prev, 0.5)
    # Entity B: flat — 2 current on 1 source (sent 0.0), 2 prior -> velocity 0
    _sig(db_session, ri1, b, cur, 0.0)
    _sig(db_session, ri1, b, cur, 0.0)
    _sig(db_session, ri1, b, prev, 0.0)
    _sig(db_session, ri1, b, prev, 0.0)
    db_session.flush()

    trends = compute_trends(db_session, 30, "30d", now=now)
    by_entity = {t.entity_id: t for t in trends}
    ta, tb = by_entity[a.id], by_entity[b.id]

    # A: 4*1 + max(3,0)*2 + 2*1.5 + 0.5*1 = 13.5
    assert ta.rank == 1
    assert ta.mention_count == 4 and ta.velocity == 3
    assert abs(ta.momentum_score - 13.5) < 1e-9
    assert abs(ta.sentiment_avg - 0.5) < 1e-9
    # B: 2*1 + 0*2 + 1*1.5 + 0 = 3.5
    assert tb.rank == 2
    assert tb.mention_count == 2 and tb.velocity == 0
    assert abs(tb.momentum_score - 3.5) < 1e-9


def test_compute_all_runs_both_windows(db_session) -> None:
    now = datetime(2026, 8, 4)
    ri1, _ri2, a, _b = _fixture(db_session)
    _sig(db_session, ri1, a, now - timedelta(days=2), 0.4)
    db_session.flush()
    counts = compute_all(session=db_session, now=now)
    assert set(counts) == {"7d", "30d"}
    assert counts["7d"] == 1 and counts["30d"] == 1
