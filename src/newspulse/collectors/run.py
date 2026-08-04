"""Collector runner.

Examples:
    python -m newspulse.collectors.run theestablished --mode news
    python -m newspulse.collectors.run theestablished --mode backfill --days 90
"""

import argparse
from datetime import date, timedelta

from newspulse.collectors.theestablished import EstablishedCollector
from newspulse.pipeline.ingest import ingest_items

COLLECTORS = {"theestablished": EstablishedCollector}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run a NewsPulse collector.")
    parser.add_argument("collector", choices=sorted(COLLECTORS))
    parser.add_argument("--mode", choices=["news", "backfill"], default="news")
    parser.add_argument("--days", type=int, default=90, help="backfill window (days)")
    args = parser.parse_args(argv)

    collector = COLLECTORS[args.collector]()
    try:
        if args.mode == "news":
            urls = collector.discover_news()
        else:
            since = date.today() - timedelta(days=args.days)
            urls = collector.discover_backfill(since)
        print(f"[{args.collector}] discovered {len(urls)} beauty URLs ({args.mode})")

        items = collector.collect_urls(urls)
        print(f"[{args.collector}] extracted {len(items)} articles with body")

        stats = ingest_items(
            items, source_url=collector.base_url, source_type="news", region="IN"
        )
        print(f"[{args.collector}] ingest: {stats}")
    finally:
        collector.close()


if __name__ == "__main__":
    main()
