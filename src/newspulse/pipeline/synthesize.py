"""Synthesis pipeline: top trends -> Trend Cards (with real citations).

For the latest snapshot of a window, take the top-N ranked trends and, for each
that has no card yet, gather its supporting articles, ask the writer for prose,
and persist a ``trend_cards`` row whose citations are the real backing articles.
Idempotent (skips trends that already have a card); audited in ``job_runs``.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newspulse.config import settings
from newspulse.db import SessionLocal
from newspulse.models import Entity, JobRun, RawItem, Signal, Trend, TrendCard
from newspulse.synth.cards import CardContext, CardWriter

EVIDENCE_LIMIT = 5


def _latest_trends(session: Session, window: str, top_n: int) -> list[Trend]:
    latest = session.execute(
        select(func.max(Trend.computed_at)).where(Trend.window == window)
    ).scalar()
    if latest is None:
        return []
    return list(
        session.execute(
            select(Trend)
            .where(Trend.window == window, Trend.computed_at == latest)
            .order_by(Trend.rank)
            .limit(top_n)
        ).scalars().all()
    )


def _evidence(session: Session, entity_id: int, limit: int = EVIDENCE_LIMIT) -> list[RawItem]:
    return list(
        session.execute(
            select(RawItem)
            .join(Signal, Signal.raw_item_id == RawItem.id)
            .where(Signal.entity_id == entity_id)
            .distinct()
            .limit(limit)
        ).scalars().all()
    )


def _has_card(session: Session, trend_id: int) -> bool:
    return session.execute(
        select(TrendCard.id).where(TrendCard.trend_id == trend_id)
    ).first() is not None


def synthesize_cards(
    writer: CardWriter,
    session: Session | None = None,
    window: str = "30d",
    top_n: int = 10,
) -> dict[str, int]:
    """Write Trend Cards for the top-N latest trends in ``window``. Returns counts."""
    own_session = session is None
    session = session or SessionLocal()
    job = JobRun(job_name="synthesize", status="started")
    session.add(job)
    session.flush()

    created = skipped = errors = tokens = 0
    try:
        for trend in _latest_trends(session, window, top_n):
            if _has_card(session, trend.id):
                skipped += 1
                continue
            entity = session.get(Entity, trend.entity_id)
            evidence = _evidence(session, trend.entity_id)
            ctx = CardContext(
                entity_name=entity.canonical_name,
                entity_type=entity.type,
                window=window,
                volume=trend.mention_count,
                velocity=trend.velocity,
                sentiment=trend.sentiment_avg,
                headlines=[ri.title for ri in evidence if ri.title],
            )
            try:
                draft = writer.write(ctx)
            except Exception:  # noqa: BLE001 - writer failed after retries; skip this card
                errors += 1
                continue

            usage = getattr(writer, "last_usage", None)
            if usage:
                tokens += int(usage.get("total_tokens") or 0)

            # Citations built from real backing articles — the model never supplies these.
            citations = [
                {"raw_item_id": ri.id, "url": ri.url, "title": ri.title} for ri in evidence
            ]
            session.add(
                TrendCard(
                    trend_id=trend.id,
                    title=draft.title,
                    body=draft.body,
                    so_what=draft.so_what,
                    citations=citations,
                    model=settings.mistral_model,
                )
            )
            created += 1

        stats = {"created": created, "skipped": skipped, "errors": errors, "tokens": tokens}
        job.status = "success"
        job.finished_at = datetime.now(UTC)
        job.stats = stats
        session.commit()
        return stats
    except Exception as exc:
        session.rollback()
        failed = JobRun(
            job_name="synthesize", status="failed", error=str(exc), finished_at=datetime.now(UTC)
        )
        session.add(failed)
        session.commit()
        raise
    finally:
        if own_session:
            session.close()
