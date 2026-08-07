"""NewsAPI poller — pull beauty news, ingest each, auto-rebuild the report.

    python -m newspulse.feeds.run --page-size 50

Needs NEWSAPI_KEY (and MISTRAL_API_KEY) in the environment.
"""

import argparse

from newspulse.db import SessionLocal
from newspulse.feeds.newsapi import NewsApiClient
from newspulse.feeds.service import ArticleFetcher, ingest_article, maybe_rebuild
from newspulse.reports.embedder import MistralEmbedder
from newspulse.reports.merger import MistralMerger
from newspulse.reports.summarizer import MistralSummarizer
from newspulse.storage import get_storage


def run_newsapi(query: str | None = None, page_size: int = 50) -> dict:
    payloads = NewsApiClient().fetch(query=query, page_size=page_size)
    session = SessionLocal()
    storage = get_storage()
    summarizer = MistralSummarizer()
    embedder = MistralEmbedder()
    fetcher = ArticleFetcher()
    counts: dict[str, int] = {}
    try:
        for payload in payloads:
            result = ingest_article(
                payload,
                session=session,
                storage=storage,
                summarizer=summarizer,
                embedder=embedder,
                fetcher=fetcher,
            )
            counts[result["status"]] = counts.get(result["status"], 0) + 1
        rebuild = maybe_rebuild(session, MistralMerger(), storage=storage)
    finally:
        fetcher.close()
        session.close()
    return {"fetched": len(payloads), "counts": counts, "rebuild": rebuild}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Poll NewsAPI for beauty news and ingest.")
    parser.add_argument("--query", default=None)
    parser.add_argument("--page-size", type=int, default=50)
    args = parser.parse_args(argv)
    print(f"[newsapi] {run_newsapi(query=args.query, page_size=args.page_size)}")


if __name__ == "__main__":
    main()
