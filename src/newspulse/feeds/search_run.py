"""Search poller — SerpAPI site-search for beauty news, ingest each hit.

    python -m newspulse.feeds.search_run --num 20
    python -m newspulse.feeds.search_run --only chosun.com/english

Needs SERPAPI_KEY (and MISTRAL_API_KEY) in the environment.
"""

import argparse

from newspulse.db import SessionLocal
from newspulse.feeds.search import SerpApiClient, load_search_sources
from newspulse.feeds.service import ArticleFetcher, ingest_article, maybe_rebuild
from newspulse.reports.embedder import MistralEmbedder
from newspulse.reports.merger import MistralMerger
from newspulse.reports.summarizer import MistralSummarizer
from newspulse.storage import get_storage


def run_search(num: int = 20, only: list[str] | None = None) -> dict:
    sources = load_search_sources()
    if only:
        sources = [s for s in sources if s.domain in only]
    client = SerpApiClient()
    session = SessionLocal()
    storage = get_storage()
    summarizer = MistralSummarizer()
    embedder = MistralEmbedder()
    fetcher = ArticleFetcher()
    counts: dict[str, int] = {}
    try:
        for source in sources:
            for payload in client.search(source, num=num):
                result = ingest_article(
                    payload, session=session, storage=storage,
                    summarizer=summarizer, embedder=embedder, fetcher=fetcher,
                )
                counts[result["status"]] = counts.get(result["status"], 0) + 1
        rebuild = maybe_rebuild(session, MistralMerger(), storage=storage)
    finally:
        fetcher.close()
        client.close()
        session.close()
    return {"counts": counts, "rebuild": rebuild}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="SerpAPI search ingestion.")
    parser.add_argument("--num", type=int, default=20)
    parser.add_argument("--only", help="comma-separated domains")
    args = parser.parse_args(argv)
    only = args.only.split(",") if args.only else None
    print(f"[search] {run_search(num=args.num, only=only)}")


if __name__ == "__main__":
    main()
