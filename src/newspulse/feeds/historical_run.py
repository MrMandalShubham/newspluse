"""Historical weekly backfill via Google News date-window search.

Pulls the last N weeks of beauty news one 7-day window at a time (Google News
honors ``after:``/``before:`` operators), so every article lands in its true
ISO week. Three market-leaning queries per week give balanced coverage across
K-/C-/J-beauty and HK/SEA; the LLM still assigns each article's country/market.
Dedup by URL is automatic, so overlapping windows don't double-ingest.

    python -m newspulse.feeds.historical_run --weeks 26 --limit 30

Needs MISTRAL_API_KEY and a browser (`playwright install chromium`). Long-running
(Playwright resolves each article) — run in the background.
"""

import argparse
from datetime import date, timedelta

import trafilatura

from newspulse.db import SessionLocal
from newspulse.feeds.googlenews import GoogleNewsClient, GoogleNewsResolver
from newspulse.feeds.service import ingest_article
from newspulse.reports.embedder import MistralEmbedder
from newspulse.reports.merger import MistralMerger
from newspulse.reports.pipeline import build_clusters, merge_clusters
from newspulse.reports.summarizer import MistralSummarizer
from newspulse.sources.extraction import extract_image
from newspulse.storage import get_storage

# Market-leaning queries (region is a fallback; LLM extracts the real country).
QUERIES: list[tuple[str, str]] = [
    ("KR", 'k-beauty OR korean skincare OR laneige OR cosrx OR "olive young" '
           'OR "beauty of joseon" OR anua OR medicube OR innisfree OR amorepacific'),
    ("CN", 'c-beauty OR chinese skincare OR florasis OR "perfect diary" OR proya '
           'OR winona OR herborist OR chando'),
    ("JP", 'j-beauty OR japanese skincare OR shiseido OR sk-ii OR "hada labo" OR kose '
           'OR canmake OR "hong kong" beauty OR "sa sa" OR indonesia skincare'),
]


def weekly_windows(
    weeks: int, end: date | None = None, offset: int = 0
) -> list[tuple[date, date]]:
    """Return [(start, end)] 7-day windows, most recent first.

    ``offset`` skips that many recent weeks (so a second run can cover the tail
    without overlapping a run already handling the newest weeks).
    """
    end = (end or date.today()) - timedelta(days=7 * offset)
    out = []
    for i in range(weeks):
        w_end = end - timedelta(days=7 * i)
        out.append((w_end - timedelta(days=7), w_end))
    return out


def run_history(
    weeks: int = 26, limit: int = 30, rebuild: bool = True, offset: int = 0
) -> dict:
    client = GoogleNewsClient()
    resolver = GoogleNewsResolver()
    session = SessionLocal()
    storage = get_storage()
    summarizer = MistralSummarizer()
    embedder = MistralEmbedder()
    totals: dict[str, int] = {}
    try:
        for w_start, w_end in weekly_windows(weeks, offset=offset):
            window = f"after:{w_start.isoformat()} before:{w_end.isoformat()}"
            for region, base_q in QUERIES:
                try:
                    items = client.search(f"{base_q} {window}", limit=limit)
                except Exception:  # noqa: BLE001 - transient network; skip this query
                    totals["query_error"] = totals.get("query_error", 0) + 1
                    continue
                for item in items:
                    try:
                        final_url, html = resolver.resolve(item["gnews_url"])
                        if not html:
                            totals["unresolved"] = totals.get("unresolved", 0) + 1
                            continue
                        payload = {
                            "url": final_url,
                            "title": item["title"],
                            "content": trafilatura.extract(html),
                            "image_url": extract_image(html),
                            "source_name": item["source_name"],
                            "published_at": (
                                item["published_at"].isoformat() if item["published_at"] else None
                            ),
                            "region": region,
                        }
                        res = ingest_article(
                            payload, session=session, storage=storage,
                            summarizer=summarizer, embedder=embedder, fetcher=None,
                        )
                        totals[res["status"]] = totals.get(res["status"], 0) + 1
                    except Exception:  # noqa: BLE001 - transient (DB/network/LLM); skip one item
                        totals["error"] = totals.get("error", 0) + 1
                        try:
                            session.rollback()
                        except Exception:  # noqa: BLE001 - dead connection; next item reconnects
                            pass
                print(f"[{w_start}..{w_end}] {region}: {len(items)} items | {totals}", flush=True)

        rebuild_stats = None
        if rebuild:
            print("[history] rebuilding clusters...", flush=True)
            clustered = build_clusters(session=session)
            merged = merge_clusters(MistralMerger(), session=session)
            rebuild_stats = {"cluster": clustered, "merge": merged}
        return {"weeks": weeks, "totals": totals, "rebuild": rebuild_stats}
    finally:
        resolver.close()
        client.close()
        session.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Historical weekly beauty-news backfill.")
    parser.add_argument("--weeks", type=int, default=26)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--offset", type=int, default=0, help="Skip this many recent weeks.")
    parser.add_argument("--no-rebuild", action="store_true")
    args = parser.parse_args(argv)
    result = run_history(
        weeks=args.weeks, limit=args.limit, rebuild=not args.no_rebuild, offset=args.offset
    )
    print(f"[history] {result}")


if __name__ == "__main__":
    main()
