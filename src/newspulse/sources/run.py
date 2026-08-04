"""Fleet runner — collect every registered source, with per-source isolation.

One broken source (layout change, timeout, 4xx) is recorded and skipped; the
rest keep going. Sources are synced from the registry first so raw_items link
to real source rows.

    python -m newspulse.sources.run --mode news
    python -m newspulse.sources.run --mode backfill --days 30
    python -m newspulse.sources.run --only theestablished
"""

import argparse
from collections.abc import Callable
from datetime import date, timedelta

from sqlalchemy.orm import Session

from newspulse.db import SessionLocal
from newspulse.pipeline.ingest import ingest_items
from newspulse.sources.collector import GenericCollector
from newspulse.sources.registry import SourceConfig, load_registry, sync_sources
from newspulse.storage import ObjectStorage


def run_fleet(
    configs: list[SourceConfig],
    session: Session,
    storage: ObjectStorage | None = None,
    mode: str = "news",
    days: int = 90,
    collector_factory: Callable[[SourceConfig], GenericCollector] = GenericCollector,
) -> dict[str, dict]:
    """Run collection for each config; isolate failures per source."""
    sync_sources(session, configs)
    results: dict[str, dict] = {}
    for cfg in configs:
        collector = collector_factory(cfg)
        try:
            if mode == "backfill":
                urls = collector.discover_backfill(date.today() - timedelta(days=days))
            else:
                urls = collector.discover()
            items = collector.collect_urls(urls)
            stats = ingest_items(
                items,
                source_url=cfg.url,
                source_type=cfg.type,
                region=cfg.region,
                session=session,
                storage=storage,
            )
            results[cfg.key] = {"status": "ok", **stats}
        except Exception as exc:  # noqa: BLE001 - isolate one source's failure
            session.rollback()
            results[cfg.key] = {"status": "failed", "error": str(exc)}
        finally:
            collector.close()
    return results


def run_from_registry(
    mode: str = "news", days: int = 90, only: list[str] | None = None
) -> dict[str, dict]:
    configs = load_registry()
    if only:
        configs = [c for c in configs if c.key in only]
    session = SessionLocal()
    try:
        return run_fleet(configs, session, mode=mode, days=days)
    finally:
        session.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the NewsPulse collector fleet.")
    parser.add_argument("--mode", choices=["news", "backfill"], default="news")
    parser.add_argument("--days", type=int, default=90, help="backfill window (days)")
    parser.add_argument("--only", help="comma-separated source keys")
    args = parser.parse_args(argv)

    only = args.only.split(",") if args.only else None
    results = run_from_registry(mode=args.mode, days=args.days, only=only)
    for key, result in results.items():
        print(f"  {key}: {result}")


if __name__ == "__main__":
    main()
