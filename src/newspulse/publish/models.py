"""Demo dashboard schema (AsiaCosmePulse "News Pulse").

These tables mirror the demo's names/columns exactly so the existing dashboard
can read our output. UUID primary keys match the demo (portable Uuid: native on
Postgres, char on SQLite). Populated by the publisher from our internal tables.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from newspulse.db import Base


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    iso_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    flag: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(300), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(300), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(300), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProductMaster(Base):
    __tablename__ = "products_master"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(500), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class NewsPulseArticle(Base):
    __tablename__ = "news_pulse_articles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    headline: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("markets.id"), nullable=True, index=True
    )
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(Text, nullable=True)
    theme: Mapped[str | None] = mapped_column(Text, nullable=True)
    reach: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic_velocity: Mapped[float | None] = mapped_column(Float, nullable=True)
    importance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class NewsArticleBrand(Base):
    __tablename__ = "news_article_brands"

    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_pulse_articles.id"), primary_key=True
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brands.id"), primary_key=True)


class NewsArticleCompany(Base):
    __tablename__ = "news_article_companies"

    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_pulse_articles.id"), primary_key=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), primary_key=True)


class NewsArticleIngredient(Base):
    __tablename__ = "news_article_ingredients"

    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_pulse_articles.id"), primary_key=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingredients.id"), primary_key=True
    )


class NewsArticleProduct(Base):
    __tablename__ = "news_article_products"

    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_pulse_articles.id"), primary_key=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products_master.id"), primary_key=True
    )
