"""Part 0.2 — structural check that all backbone tables are registered."""

import newspulse.models  # noqa: F401  (registers tables on Base.metadata)
from newspulse.db import Base

EXPECTED_TABLES = {
    "sources",
    "raw_items",
    "entities",
    "signals",
    "trends",
    "trend_cards",
    "job_runs",
}


def test_all_tables_registered() -> None:
    assert EXPECTED_TABLES <= set(Base.metadata.tables)
