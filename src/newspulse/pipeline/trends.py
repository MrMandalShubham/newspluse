"""Trend engine — deterministic momentum scoring over time windows.

For each entity we compare its signal volume in the current window against the
prior window of equal length. Momentum rewards raw volume, positive *velocity*
(the real trend signal), cross-source breadth, and sentiment:

    momentum = volume*Wv + max(velocity,0)*Wvel + breadth*Wb + sentiment*Ws

No AI here — it's reproducible and explainable, which is what B2B buyers need
when they ask "why is this ranked #1". Each run writes a fresh snapshot of
``trends`` rows (ranked) and is audited in ``job_runs``.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from newspulse.db import SessionLocal
from newspulse.models import JobRun, RawItem, Signal, Trend

# Scoring weights (velocity weighted highest — rate of change is the signal).
W_VOLUME = 1.0
W_VELOCITY = 2.0
W_BREADTH = 1.5
W_SENTIMENT = 1.0

WINDOWS = {"7d": 7, "30d": 30}


def _rows_between(session: Session, start: datetime, end: datetime):
    """(entity_id, source_id, sentiment) for signals with start <= observed_at < end."""
    return session.execute(
        select(Signal.entity_id, RawItem.source_id, Signal.sentiment)
        .join(RawItem, Signal.raw_item_id == RawItem.id)
        .where(Signal.observed_at >= start, Signal.observed_at < end)
    ).all()


def compute_trends(
    session: Session, window_days: int, label: str, now: datetime | None = None
) -> list[Trend]:
    """Compute + persist ranked trends for one window. Returns the Trend rows."""
    now = now or datetime.now(UTC)
    cur_start = now - timedelta(days=window_days)
    prev_start = now - timedelta(days=2 * window_days)

    current: dict[int, dict] = defaultdict(lambda: {"count": 0, "sources": set(), "sent": []})
    for entity_id, source_id, sentiment in _rows_between(session, cur_start, now):
        agg = current[entity_id]
        agg["count"] += 1
        agg["sources"].add(source_id)
        if sentiment is not None:
            agg["sent"].append(sentiment)

    prior: dict[int, int] = defaultdict(int)
    for entity_id, _source_id, _sentiment in _rows_between(session, prev_start, cur_start):
        prior[entity_id] += 1

    scored = []
    for entity_id, agg in current.items():
        volume = agg["count"]
        velocity = volume - prior.get(entity_id, 0)
        breadth = len(agg["sources"])
        sent_avg = sum(agg["sent"]) / len(agg["sent"]) if agg["sent"] else None
        score = (
            volume * W_VOLUME
            + max(velocity, 0) * W_VELOCITY
            + breadth * W_BREADTH
            + (sent_avg or 0.0) * W_SENTIMENT
        )
        scored.append(
            {
                "entity_id": entity_id,
                "volume": volume,
                "velocity": velocity,
                "sent_avg": sent_avg,
                "score": score,
            }
        )

    # Rank by score, then volume as a stable tie-breaker.
    scored.sort(key=lambda r: (r["score"], r["volume"]), reverse=True)

    trends: list[Trend] = []
    for rank, r in enumerate(scored, start=1):
        trend = Trend(
            entity_id=r["entity_id"],
            window=label,
            mention_count=r["volume"],
            velocity=r["velocity"],
            momentum_score=r["score"],
            sentiment_avg=r["sent_avg"],
            rank=rank,
            computed_at=now,
        )
        session.add(trend)
        trends.append(trend)
    session.flush()
    return trends


def compute_all(session: Session | None = None, now: datetime | None = None) -> dict[str, int]:
    """Compute trends for every configured window. Returns per-window counts."""
    own_session = session is None
    session = session or SessionLocal()
    job = JobRun(job_name="trends", status="started")
    session.add(job)
    session.flush()
    try:
        counts = {
            label: len(compute_trends(session, days, label, now=now))
            for label, days in WINDOWS.items()
        }
        job.status = "success"
        job.finished_at = datetime.now(UTC)
        job.stats = counts
        session.commit()
        return counts
    except Exception as exc:
        session.rollback()
        failed = JobRun(
            job_name="trends", status="failed", error=str(exc), finished_at=datetime.now(UTC)
        )
        session.add(failed)
        session.commit()
        raise
    finally:
        if own_session:
            session.close()


def main() -> None:
    print(f"[trends] {compute_all()}")


if __name__ == "__main__":
    main()
