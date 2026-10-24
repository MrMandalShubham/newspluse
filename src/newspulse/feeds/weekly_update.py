"""Automated daily article update — runs the full pipeline.

Pulls articles from three source types (Google News broad queries, RSS feeds,
and Google News site-search), enriches with AI, clusters into stories/topics,
and publishes to the platform DB.

    python -m newspulse.feeds.weekly_update

Designed to run 2x daily (02:37 + 14:37 SGT/HKT) via GitHub Actions.
"""

import sys
import time
from datetime import date, timedelta

from newspulse.feeds.historical_run import run_history
from newspulse.feeds.html_fetcher import fetch_html_sources
from newspulse.feeds.load_sources import (
    disable_dead_sources,
    fix_htmlcrawl_sources,
    fix_rss_sources,
)
from newspulse.feeds.rss_fetcher import fetch_rss_sources
from newspulse.feeds.site_search_fetcher import fetch_site_search_sources
from newspulse.publish.platform import (
    publish_to_platform,
    publish_topic_clusters,
    refresh_platform_signals,
)


def daily_update() -> dict:
    start = time.time()
    results: dict = {}
    total_ingested = 0

    today = date.today()
    yesterday = today - timedelta(days=1)
    print(f"[daily] Starting update: {yesterday} -> {today}", flush=True)

    # --- Step 0: Ensure sources with known RSS/html_crawl feeds are correctly classified ---
    try:
        rss_fix = fix_rss_sources()
        if rss_fix["fixed"]:
            results["rss_fix"] = rss_fix
    except Exception as e:
        print(f"[daily] WARNING: RSS source fix failed: {e}", flush=True)

    try:
        html_fix = fix_htmlcrawl_sources()
        if html_fix["fixed"]:
            results["html_fix"] = html_fix
    except Exception as e:
        print(f"[daily] WARNING: html_crawl source fix failed: {e}", flush=True)

    try:
        dead_fix = disable_dead_sources()
        if dead_fix["disabled"]:
            results["dead_fix"] = dead_fix
    except Exception as e:
        print(f"[daily] WARNING: disable dead sources failed: {e}", flush=True)

    # --- Source 1: Google News broad queries (existing 6-market queries) ---
    print("[daily] Step 1/7: Pulling articles from Google News...", flush=True)
    try:
        history = run_history(weeks=1, limit=20, rebuild=True, offset=0)
        results["ingest"] = history["totals"]
        results["clusters_built"] = history.get("rebuild")
        ingested = history["totals"].get("ingested", 0)
        duplicates = history["totals"].get("duplicate", 0)
        total_ingested += ingested
        print(f"[daily] Google News: {ingested} new, {duplicates} duplicates", flush=True)
    except Exception as e:
        print(f"[daily] FATAL: Google News ingestion failed: {e}", flush=True)
        results["error"] = str(e)

    # --- Source 2: RSS feeds (Class A) ---
    print("[daily] Step 2/7: Fetching RSS feeds...", flush=True)
    try:
        rss = fetch_rss_sources()
        results["rss"] = rss
        rss_ingested = rss["totals"].get("ingested", 0)
        total_ingested += rss_ingested
        print(f"[daily] RSS: {rss_ingested} new from {rss['sources']} feeds", flush=True)
    except Exception as e:
        print(f"[daily] ERROR: RSS fetch failed: {e}", flush=True)
        results["rss_error"] = str(e)

    # --- Source 3: HTML crawl (Class E — no RSS, not on Google News) ---
    print("[daily] Step 3/7: Crawling HTML article listings...", flush=True)
    try:
        html = fetch_html_sources()
        results["html_crawl"] = html
        html_ingested = html["totals"].get("ingested", 0)
        total_ingested += html_ingested
        print(f"[daily] HTML crawl: {html_ingested} new from {html['sources']} sources", flush=True)
    except Exception as e:
        print(f"[daily] ERROR: HTML crawl failed: {e}", flush=True)
        results["html_crawl_error"] = str(e)

    # --- Source 4: Google News site-search (Class D) ---
    print("[daily] Step 4/7: Running site-specific searches...", flush=True)
    try:
        site = fetch_site_search_sources()
        results["site_search"] = site
        site_ingested = site["totals"].get("ingested", 0)
        total_ingested += site_ingested
        print(f"[daily] Site-search: {site_ingested} new from {site['sources']} srcs", flush=True)
    except Exception as e:
        print(f"[daily] ERROR: site-search failed: {e}", flush=True)
        results["site_search_error"] = str(e)

    if total_ingested == 0:
        print("[daily] No new articles from any source -- skipping publish", flush=True)
        results["publish"] = "skipped"
        return results

    since = today - timedelta(days=3)
    print(f"[daily] Publishing only articles since {since} (3-day window)", flush=True)

    print("[daily] Step 5/7: Publishing articles to platform DB...", flush=True)
    try:
        pub = publish_to_platform(since=since)
        results["publish"] = pub
        print(f"[daily] Published {pub.get('articles', 0)} articles", flush=True)
    except Exception as e:
        print(f"[daily] ERROR: publish failed: {e}", flush=True)
        results["publish_error"] = str(e)

    print("[daily] Step 6/7: Refreshing signals...", flush=True)
    try:
        sig = refresh_platform_signals(since=since)
        results["signals"] = sig
        print(f"[daily] Updated {sig.get('updated', 0)} signals", flush=True)
    except Exception as e:
        print(f"[daily] ERROR: signals failed: {e}", flush=True)
        results["signals_error"] = str(e)

    print("[daily] Step 7/7: Publishing topic clusters...", flush=True)
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
