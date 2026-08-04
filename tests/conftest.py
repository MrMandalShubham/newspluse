"""Shared test fixtures."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import newspulse.models  # noqa: F401  (registers tables on Base.metadata)
from newspulse.db import Base


@pytest.fixture
def db_session() -> Iterator[Session]:
    """An isolated in-memory SQLite session with all tables created."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
