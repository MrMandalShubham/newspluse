"""Enrichment runner.

    python -m newspulse.enrich.run            # enrich all pending raw items
    python -m newspulse.enrich.run --limit 5  # cap for a quick/cheap test
"""

import argparse

from newspulse.enrich.llm import MistralExtractor
from newspulse.pipeline.enrich import enrich_pending


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run NewsPulse enrichment.")
    parser.add_argument("--limit", type=int, default=None, help="max items to enrich")
    args = parser.parse_args(argv)

    stats = enrich_pending(MistralExtractor(), limit=args.limit)
    print(f"[enrich] {stats}")


if __name__ == "__main__":
    main()
