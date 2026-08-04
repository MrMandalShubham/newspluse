"""Enrichment: raw_items -> structured signals.

For each raw item that has no signals yet, load its stored body, ask the
extractor for entity mentions, resolve each to a canonical entity, and write
``signals`` rows. Idempotent: items already enriched are skipped, so re-running
is safe. Every run is audited in ``job_runs``.
"""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newspulse.db import SessionLocal
from newspulse.enrich.entities import EntityResolver
from newspulse.enrich.llm import SignalExtractor
from newspulse.models import JobRun, RawItem, Signal
from newspulse.storage import ObjectStorage, get_storage


def _pending(session: Session) -> list[RawItem]:
    """Raw items that have no signals yet."""
    stmt = select(RawItem).where(
        ~select(Signal.id).where(Signal.raw_item_id == RawItem.id).exists()
    )
    return list(session.execute(stmt).scalars().all())


def _storage_key(raw_ref: str | None) -> str:
    return (raw_ref or "").split("://", 1)[-1]


def enrich_pending(
    extractor: SignalExtractor,
    session: Session | None = None,
    storage: ObjectStorage | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Extract signals for all un-enriched raw items. Returns counts."""
    own_session = session is None
    session = session or SessionLocal()
    storage = storage or get_storage()
    resolver = EntityResolver(session)

    job = JobRun(job_name="enrich", status="started")
    session.add(job)
    session.flush()

    items = _pending(session)
    if limit is not None:
        items = items[:limit]

    processed = signals_created = errors = tokens = 0
    try:
        for item in items:
            try:
                payload = json.loads(storage.get(_storage_key(item.raw_ref)))
            except Exception:  # noqa: BLE001 - missing/broken payload, skip item
                continue

            try:
                result = extractor.extract(
                    payload.get("title"),
                    payload.get("body") or "",
                    payload.get("keywords") or [],
                )
            except Exception:  # noqa: BLE001 - LLM call failed after retries; skip item
                errors += 1
                continue

            usage = getattr(extractor, "last_usage", None)
            if usage:
                tokens += int(usage.get("total_tokens") or 0)

            for m in result.mentions:
                entity = resolver.resolve(m.name, m.type)
                session.add(
                    Signal(
                        raw_item_id=item.id,
                        entity_id=entity.id,
                        signal_type=m.signal_type,
                        sentiment=m.sentiment,
                        weight=1.0,
                    )
                )
                signals_created += 1
            processed += 1

        stats = {
            "processed": processed,
            "signals": signals_created,
            "errors": errors,
            "tokens": tokens,
        }
        job.status = "success"
        job.finished_at = datetime.now(UTC)
        job.stats = stats
        session.commit()
        return stats
    except Exception as exc:
        session.rollback()
        failed = JobRun(
            job_name="enrich",
            status="failed",
            error=str(exc),
            finished_at=datetime.now(UTC),
        )
        session.add(failed)
        session.commit()
        raise
    finally:
        if own_session:
            session.close()
