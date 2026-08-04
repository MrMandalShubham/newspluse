"""Synthesis runner.

    python -m newspulse.synth.run --window 30d --top 10
"""

import argparse

from newspulse.pipeline.synthesize import synthesize_cards
from newspulse.synth.cards import MistralCardWriter


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate Trend Cards.")
    parser.add_argument("--window", default="30d", choices=["7d", "30d"])
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)

    stats = synthesize_cards(MistralCardWriter(), window=args.window, top_n=args.top)
    print(f"[synthesize] {stats}")


if __name__ == "__main__":
    main()
