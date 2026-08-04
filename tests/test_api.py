"""Phase 5.1 — API contract tests over a seeded in-memory DB."""

from datetime import datetime

from fastapi.testclient import TestClient

from newspulse.db import get_session
from newspulse.main import app
from newspulse.models import Entity, RawItem, Signal, Source, Trend, TrendCard


def _seed(session) -> Trend:
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
        entity_id=ent.id, window="30d", mention_count=3, velocity=3.0,
        momentum_score=10.5, rank=1, computed_at=datetime(2026, 8, 4),
    )
    session.add(trend)
    session.flush()
    session.add(
        TrendCard(
            trend_id=trend.id,
            title="Salicylic acid is surging",
            body="Because reasons.",
            so_what="Stock it.",
            citations=[
                {"raw_item_id": ri.id, "url": "https://e/a", "title": "Salicylic acid guide"}
            ],
            model="mistral-small-latest",
        )
    )
    session.commit()
    return trend


def _client(db_session) -> TestClient:
    def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    return TestClient(app)


def test_list_trends(db_session) -> None:
    _seed(db_session)
    try:
        resp = _client(db_session).get("/trends?window=30d")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["entity_name"] == "salicylic acid"
        assert data[0]["rank"] == 1
        assert data[0]["momentum_score"] == 10.5
    finally:
        app.dependency_overrides.clear()


def test_trend_detail_includes_cards(db_session) -> None:
    trend = _seed(db_session)
    try:
        resp = _client(db_session).get(f"/trends/{trend.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_name"] == "salicylic acid"
        assert len(data["cards"]) == 1
        assert data["cards"][0]["title"] == "Salicylic acid is surging"
        assert data["cards"][0]["citations"][0]["url"] == "https://e/a"
    finally:
        app.dependency_overrides.clear()


def test_list_cards(db_session) -> None:
    _seed(db_session)
    try:
        resp = _client(db_session).get("/cards?window=30d")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["so_what"] == "Stock it."
    finally:
        app.dependency_overrides.clear()


def test_report_latest_markdown(db_session) -> None:
    _seed(db_session)
    try:
        resp = _client(db_session).get("/report/latest?window=30d")
        assert resp.status_code == 200
        body = resp.text
        assert "Beauty Trend Report" in body
        assert "Salicylic acid is surging" in body
        assert "https://e/a" in body  # citation present
    finally:
        app.dependency_overrides.clear()


def test_trend_not_found(db_session) -> None:
    try:
        resp = _client(db_session).get("/trends/999")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
