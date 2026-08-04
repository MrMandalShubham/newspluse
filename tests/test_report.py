"""Phase 5.2 — report rendering + file generation."""

from datetime import datetime

from newspulse.models import Entity, RawItem, Signal, Source, Trend, TrendCard
from newspulse.pipeline.report import render_report, write_report


class DictStorage:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> str:
        self.data[key] = data
        return f"local://{key}"

    def get(self, key: str) -> bytes:
        return self.data[key]


def _seed(session) -> None:
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


def test_render_report_has_cards_and_citations(db_session) -> None:
    _seed(db_session)
    md = render_report(db_session, "30d", 10)
    assert "# NewsPulse — Beauty Trend Report (30d)" in md
    assert "1. Salicylic acid is surging" in md
    assert "**So what:** Stock it." in md
    assert "[Salicylic acid guide](https://e/a)" in md


def test_render_report_empty_window(db_session) -> None:
    assert render_report(db_session, "7d", 10) == ""


def test_write_report_persists_file(db_session) -> None:
    _seed(db_session)
    storage = DictStorage()
    ref, md = write_report(session=db_session, window="30d", storage=storage)
    assert ref == "local://reports/30d-latest.md"
    assert storage.get("reports/30d-latest.md").decode("utf-8") == md
    assert "Salicylic acid is surging" in md
