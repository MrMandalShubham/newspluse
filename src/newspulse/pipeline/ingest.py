"""Ingestion: persist collected items into storage + Postgres.

Each item's raw payload (title, body, keywords, dates) is written to object
storage keyed by a content hash; only metadata + a ``raw_ref`` pointer go into
``raw_items``. Dedup is by ``content_hash`` (derived from the article URL), so
re-running is safe and idempotent. Every run is audited in ``job_runs``.
"""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newspulse.collectors.base import CollectedItem, content_hash
from newspulse.db import SessionLocal
from newspulse.models import JobRun, RawItem, Source
from newspulse.storage import ObjectStorage, get_storage


def get_or_create_source(
    session: Session, name: str, url: str, source_type: str, region: str | None
) -> Source:
    src = session.execute(select(Source).where(Source.name == name)).scalar_one_or_none()
    if src is None:
        src = Source(name=name, url=url, type=source_type, region=region)
        session.add(src)
        session.flush()
    return src


def ingest_items(
    items: list[CollectedItem],
    source_url: str,
    source_type: str = "news",
    region: str | None = None,
    session: Session | None = None,
    storage: ObjectStorage | None = None,
) -> dict[str, int]:
    """Persist items; return counts. Safe to re-run (dedup by content hash)."""
    own_session = session is None
    session = session or SessionLocal()
    storage = storage or get_storage()
    job = JobRun(job_name="ingest", status="started")
    session.add(job)
    session.flush()

    inserted = skipped = 0
    seen_hashes: set[str] = set()
    try:
        for item in items:
            src = get_or_create_source(session, item.source_name, source_url, source_type, region)
            h = content_hash(item.url)

            already = session.execute(
                select(RawItem.id).where(RawItem.content_hash == h)
            ).first()
            if h in seen_hashes or already:
                skipped += 1
                continue
            seen_hashes.add(h)

            payload = json.dumps(item.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
            raw_ref = storage.put(f"{h}.json", payload)
            session.add(
                RawItem(
                    source_id=src.id,
                    url=item.url,
                    title=item.title,
                    content_hash=h,
                    raw_ref=raw_ref,
                    image_url=item.image_url,
                    lang=item.lang,
                    published_at=item.published_at,
                )
            )
            inserted += 1

        job.status = "success"
        job.finished_at = datetime.now(UTC)
        job.stats = {"seen": len(items), "inserted": inserted, "skipped": skipped}
        session.commit()
        return {"seen": len(items), "inserted": inserted, "skipped": skipped}
    except Exception as exc:
        session.rollback()
        failed = JobRun(
            job_name="ingest",
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
