"""Publisher runner — write product articles into the demo dashboard schema.

    python -m newspulse.publish.run
"""

from newspulse.publish.publisher import publish


def main() -> None:
    print(f"[publish] {publish()}")


if __name__ == "__main__":
    main()
