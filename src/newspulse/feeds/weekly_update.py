"""Automated daily article update — runs the full pipeline.

Pulls the past day's articles across all markets, enriches with AI,
clusters into stories/topics, and publishes to the platform DB.

    python -m newspulse.feeds.weekly_update

Designed to run daily at 4 AM HKT via GitHub Actions.
"""

import sys
import time
from datetime import date, timedelta

from newspulse.feeds.historical_run import run_history
from newspulse.publish.platform import (
    publish_to_platform,
    publish_topic_clusters,
    refresh_platform_signals,
)


def daily_update() -> dict:
    start = time.time()
    results: dict = {}

    today = date.today()
    yesterday = today - timedelta(days=1)
    print(f"[daily] Starting update: {yesterday} -> {today}", flush=True)

    print("[daily] Step 1/4: Pulling articles from Google News...", flush=True)
    try:
        history = run_history(weeks=1, limit=20, rebuild=True, offset=0)
        results["ingest"] = history["totals"]
        results["clusters_built"] = history.get("rebuild")
        ingested = history["totals"].get("ingested", 0)
        duplicates = history["totals"].get("duplicate", 0)
        print(f"[daily] Ingested {ingested} new, {duplicates} duplicates", flush=True)
    except Exception as e:
        print(f"[daily] FATAL: ingestion failed: {e}", flush=True)
        results["error"] = str(e)
        return results

    if ingested == 0:
        print("[daily] No new articles -- skipping publish", flush=True)
        results["publish"] = "skipped"
        return results

    since = today - timedelta(days=3)
    print(f"[daily] Publishing only articles since {since} (3-day window)", flush=True)

    print("[daily] Step 2/4: Publishing articles to platform DB...", flush=True)
    try:
        pub = publish_to_platform(since=since)
        results["publish"] = pub
        print(f"[daily] Published {pub.get('articles', 0)} articles", flush=True)
    except Exception as e:
        print(f"[daily] ERROR: publish failed: {e}", flush=True)
        results["publish_error"] = str(e)

    print("[daily] Step 3/4: Refreshing signals...", flush=True)
    try:
        sig = refresh_platform_signals(since=since)
        results["signals"] = sig
        print(f"[daily] Updated {sig.get('updated', 0)} signals", flush=True)
    except Exception as e:
        print(f"[daily] ERROR: signals failed: {e}", flush=True)
        results["signals_error"] = str(e)

    print("[daily] Step 4/4: Publishing topic clusters...", flush=True)
    try:
        tc = publish_topic_clusters()
        results["topic_clusters"] = tc
        clusters, members = tc.get("clusters", 0), tc.get("members", 0)
        print(f"[daily] {clusters} clusters, {members} members", flush=True)
    except Exception as e:
        print(f"[daily] ERROR: topic clusters failed: {e}", flush=True)
        results["topic_clusters_error"] = str(e)

    elapsed = round(time.time() - start, 1)
    results["elapsed_seconds"] = elapsed
    print(f"[daily] Complete in {elapsed}s", flush=True)
    return results


def main() -> None:
    result = daily_update()

    errors = [k for k in result if k.endswith("_error")]
    if errors:
        print(f"\n[daily] FINISHED WITH ERRORS: {errors}")
        print(f"[daily] Result: {result}")
        sys.exit(1)

    print(f"\n[daily] SUCCESS: {result}")


if __name__ == "__main__":
    main()
