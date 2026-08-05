"""Product-report pipeline runner: summarize -> embed -> cluster -> merge -> report.

    python -m newspulse.reports.run
    python -m newspulse.reports.run --threshold 0.85
"""

import argparse

from newspulse.reports.embedder import MistralEmbedder
from newspulse.reports.merger import MistralMerger
from newspulse.reports.pipeline import (
    build_clusters,
    embed_pending,
    merge_clusters,
    summarize_pending,
)
from newspulse.reports.render import write_product_report
from newspulse.reports.summarizer import MistralSummarizer


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the product-news report.")
    parser.add_argument("--threshold", type=float, default=0.82, help="clustering similarity")
    args = parser.parse_args(argv)

    print("summarize:", summarize_pending(MistralSummarizer()))
    print("embed:", embed_pending(MistralEmbedder()))
    print("cluster:", build_clusters(threshold=args.threshold))
    print("merge:", merge_clusters(MistralMerger()))
    ref, markdown = write_product_report()
    print(f"report: wrote {ref} ({len(markdown)} chars)")


if __name__ == "__main__":
    main()
