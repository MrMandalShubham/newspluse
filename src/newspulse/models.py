"""ORM models — the storage backbone.

Seven tables mirror the pipeline in ARCHITECTURE.md:

    sources -> raw_items -> signals -> trends -> trend_cards
    entities (normalized dictionary, referenced by signals/trends)
    job_runs (audit of every pipeline run)

Types are kept cross-dialect (generic JSON, DateTime(timezone=True)) so the same
migrations apply on both SQLite (local smoke) and Postgres (Docker / DO).
The pgvector embedding column is intentionally deferred to Phase 2.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newspulse.db import Base


class Source(Base):
    """A registered data source (news feed, retailer, regulator)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    url: Mapped[str] = mapped_column(String(1000))
    type: Mapped[str] = mapped_column(String(30))  # news | retail | social | reg
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    trust_score: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    raw_items: Mapped[list["RawItem"]] = relationship(back_populates="source")


class RawItem(Base):
    """A single collected item. Full text lives in object storage (raw_ref)."""

    __tablename__ = "raw_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    raw_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)  # Spaces key
    lang: Mapped[str | None] = mapped_column(String(10), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    source: Mapped["Source"] = relationship(back_populates="raw_items")
    signals: Mapped[list["Signal"]] = relationship(back_populates="raw_item")


class Entity(Base):
    """A normalized entity: brand, product, ingredient, or category."""

    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("type", "canonical_name", name="uq_entity_type_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(30))  # brand | product | ingredient | category
    canonical_name: Mapped[str] = mapped_column(String(300))
    aliases: Mapped[list | None] = mapped_column(JSON, default=list)
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Signal(Base):
    """An extracted fact linking a raw item to an entity."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_items.id"), index=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    signal_type: Mapped[str] = mapped_column(String(30))  # launch|mention|review|ranking|price|reg
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)  # -1..1
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    raw_item: Mapped["RawItem"] = relationship(back_populates="signals")


class Trend(Base):
    """A computed trend for an entity over a time window."""

    __tablename__ = "trends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    window: Mapped[str] = mapped_column(String(10))  # 7d | 30d
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    velocity: Mapped[float] = mapped_column(Float, default=0.0)
    momentum_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    sentiment_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    cards: Mapped[list["TrendCard"]] = relationship(back_populates="trend")


class TrendCard(Base):
    """A synthesized, sellable insight with mandatory citations."""

    __tablename__ = "trend_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trend_id: Mapped[int] = mapped_column(ForeignKey("trends.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    so_what: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list | None] = mapped_column(JSON, default=list)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    trend: Mapped["Trend"] = relationship(back_populates="cards")


class JobRun(Base):
    """Audit record for every pipeline stage run (idempotency + observability)."""

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20))  # started | success | failed
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
