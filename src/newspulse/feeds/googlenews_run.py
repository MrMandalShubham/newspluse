"""Google News (keyless) runner — search K-beauty, resolve, ingest, rebuild.

    python -m newspulse.feeds.googlenews_run --limit 15

Needs MISTRAL_API_KEY (and a browser: `playwright install chromium`). No search key.
"""

import argparse

import trafilatura

from newspulse.db import SessionLocal
from newspulse.feeds.googlenews import GoogleNewsClient, GoogleNewsResolver
from newspulse.feeds.service import batch_ingest, ingest_article_raw, maybe_rebuild
from newspulse.reports.embedder import MistralEmbedder
from newspulse.reports.merger import MistralMerger
from newspulse.reports.summarizer import MistralSummarizer
from newspulse.sources.extraction import extract_image
from newspulse.storage import get_storage

# Biased toward Korean brands that are in the OliveYoung / K-beauty catalog.
DEFAULT_QUERY = (
    "k-beauty OR korean skincare OR korean beauty OR amorepacific OR laneige "
    "OR innisfree OR cosrx OR sulwhasoo OR \"olive young\""
)


def run_googlenews(
    query: str = DEFAULT_QUERY, region: str = "KR", limit: int = 15, raw: bool = False
) -> dict:
    client = GoogleNewsClient()
    resolver = GoogleNewsResolver()
    session = SessionLocal()
    storage = get_storage()
    summarizer = None if raw else MistralSummarizer()
    embedder = None if raw else MistralEmbedder()
    counts: dict[str, int] = {}
    items = client.search(query, limit=limit)
    try:
        all_payloads: list[dict] = []
        for item in items:
            final_url, html = resolver.resolve(item["gnews_url"])
            if not html:
                counts["unresolved"] = counts.get("unresolved", 0) + 1
                continue
            body = trafilatura.extract(html)
            payload = {
                "url": final_url,
                "title": item["title"],
                "content": body,
                "image_url": extract_image(html),
                "source_name": item["source_name"],
                "published_at": item["published_at"].isoformat() if item["published_at"] else None,
                "region": region,
            }
            if raw:
                result = ingest_article_raw(payload, session=session, storage=storage, fetcher=None)
                counts[result["status"]] = counts.get(result["status"], 0) + 1
            else:
                all_payloads.append(payload)

        if not raw and all_payloads:
            batch_counts = batch_ingest(
                all_payloads, session=session, storage=storage,
                summarizer=summarizer, embedder=embedder,
            )
            for k, v in batch_counts.items():
                counts[k] = counts.get(k, 0) + v

        rebuild = None if raw else maybe_rebuild(session, MistralMerger(), storage=storage)
    finally:
        resolver.close()
        client.close()
        session.close()
    return {"fetched": len(items), "counts": counts, "rebuild": rebuild}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Keyless Google News beauty ingestion.")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--region", default="KR")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--raw", action="store_true", help="Store raw only (no LLM enrichment).")
    args = parser.parse_args(argv)
    print(
        f"[googlenews] "
        f"{run_googlenews(query=args.query, region=args.region, limit=args.limit, raw=args.raw)}"
    )


if __name__ == "__main__":
    main()
