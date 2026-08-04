"""Database engine, session factory, and declarative base.

The engine is created lazily-connecting: importing this module does NOT open a
connection, so tests and tooling can import models without a live database.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from newspulse.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_session() -> Iterator[Session]:
    """Yield a database session (FastAPI dependency-friendly)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
