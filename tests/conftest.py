"""Shared test fixtures."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import newspulse.models  # noqa: F401  (registers tables on Base.metadata)
import newspulse.publish.models  # noqa: F401  (registers demo tables on Base.metadata)
from newspulse.db import Base


@pytest.fixture
def db_session() -> Iterator[Session]:
    """An isolated in-memory SQLite session with all tables created.

    StaticPool + check_same_thread=False keeps a single shared connection so the
    same in-memory DB is visible from FastAPI's TestClient worker thread too.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
