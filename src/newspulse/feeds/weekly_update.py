"""Automated weekly article update — runs the full pipeline.

Pulls the past week's articles across all markets, enriches with AI,
clusters into stories/topics, and publishes to the platform DB.

    python -m newspulse.feeds.weekly_update

Designed to run every Saturday via GitHub Actions or cron.
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


def weekly_update() -> dict:
    start = time.time()
    results: dict = {}

    today = date.today()
    week_ago = today - timedelta(days=7)
    print(f"[weekly] Starting update: {week_ago} → {today}", flush=True)

    print("[weekly] Step 1/4: Pulling articles from Google News...", flush=True)
    try:
        history = run_history(weeks=1, limit=30, rebuild=True, offset=0)
        results["ingest"] = history["totals"]
        results["clusters_built"] = history.get("rebuild")
        ingested = history["totals"].get("ingested", 0)
        duplicates = history["totals"].get("duplicate", 0)
        print(f"[weekly] Ingested {ingested} new, {duplicates} duplicates", flush=True)
    except Exception as e:
        print(f"[weekly] FATAL: ingestion failed: {e}", flush=True)
        results["error"] = str(e)
        return results

    if ingested == 0:
        print("[weekly] No new articles — skipping publish", flush=True)
        results["publish"] = "skipped"
        return results

    print("[weekly] Step 2/4: Publishing articles to platform DB...", flush=True)
    try:
        pub = publish_to_platform()
        results["publish"] = pub
        print(f"[weekly] Published {pub.get('articles', 0)} articles", flush=True)
    except Exception as e:
        print(f"[weekly] ERROR: publish failed: {e}", flush=True)
        results["publish_error"] = str(e)

    print("[weekly] Step 3/4: Refreshing signals...", flush=True)
    try:
        sig = refresh_platform_signals()
        results["signals"] = sig
        print(f"[weekly] Updated {sig.get('updated', 0)} signals", flush=True)
    except Exception as e:
        print(f"[weekly] ERROR: signals failed: {e}", flush=True)
        results["signals_error"] = str(e)

    print("[weekly] Step 4/4: Publishing topic clusters...", flush=True)
    try:
        tc = publish_topic_clusters()
        results["topic_clusters"] = tc
        print(f"[weekly] {tc.get('clusters', 0)} clusters, {tc.get('members', 0)} members", flush=True)
    except Exception as e:
        print(f"[weekly] ERROR: topic clusters failed: {e}", flush=True)
        results["topic_clusters_error"] = str(e)

    elapsed = round(time.time() - start, 1)
    results["elapsed_seconds"] = elapsed
    print(f"[weekly] Complete in {elapsed}s", flush=True)
    return results


def main() -> None:
    result = weekly_update()

    errors = [k for k in result if k.endswith("_error")]
    if errors:
        print(f"\n[weekly] FINISHED WITH ERRORS: {errors}")
        print(f"[weekly] Result: {result}")
        sys.exit(1)

    print(f"\n[weekly] SUCCESS: {result}")


if __name__ == "__main__":
    main()
