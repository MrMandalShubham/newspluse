"""Demo dashboard schema (AsiaCosmePulse "News Pulse").

These tables mirror the demo's names/columns exactly so the existing dashboard
can read our output. UUID primary keys match the demo (portable Uuid: native on
Postgres, char on SQLite). Populated by the publisher from our internal tables.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.orm import Mapped, mapped_column

from newspulse.db import Base

_JSONB = JSON().with_variant(PG_JSONB, "postgresql")


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
    story_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    headline: Mapped[str] = mapped_column(Text)
    headline_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
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


class TopicCluster(Base):
    __tablename__ = "topic_clusters"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    primary_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    primary_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_mixed_country: Mapped[bool] = mapped_column(default=False)
    is_mixed_category: Mapped[bool] = mapped_column(default=False)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    velocity: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TopicClusterMember(Base):
    __tablename__ = "topic_cluster_members"

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topic_clusters.id", ondelete="CASCADE"), primary_key=True
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_pulse_articles.id", ondelete="CASCADE"), primary_key=True
    )
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint(
            "source IN ('news-pulse','newsletter','contact-form',"
            "'agency-site','download-report','other')",
            name="leads_source_check",
        ),
        CheckConstraint(
            "status IN ('pending','confirmed','subscribed',"
            "'unsubscribed','converted','bounced')",
            name="leads_status_check",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    company: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_interest: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    token: Mapped[str | None] = mapped_column(Text, nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_tool_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    utm_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    unsubscribed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_email_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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


class Theme(Base):
    __tablename__ = "themes"
    __table_args__ = (
        CheckConstraint(
            "type IN ('ingredient','claim','macro-trend','micro-trend',"
            "'segment','format','channel','need','value','geography',"
            "'regulatory','sustainability')",
            name="themes_type_check",
        ),
        CheckConstraint(
            "lifecycle IN ('emerging','growth','mature','declining')",
            name="themes_lifecycle_check",
        ),
        CheckConstraint(
            "status IN ('active','draft','archived')",
            name="themes_status_check",
        ),
        Index("ix_themes_type", "type"),
        Index("ix_themes_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    label_en: Mapped[str] = mapped_column(String(300), nullable=False)
    label_fr: Mapped[str | None] = mapped_column(String(300), nullable=True)
    label_kr: Mapped[str | None] = mapped_column(String(300), nullable=True)
    label_jp: Mapped[str | None] = mapped_column(String(300), nullable=True)
    label_zh: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    facet_geography: Mapped[list | None] = mapped_column(_JSONB, nullable=True)
    facet_category: Mapped[list | None] = mapped_column(_JSONB, nullable=True)
    facet_need: Mapped[list | None] = mapped_column(_JSONB, nullable=True)
    facet_ingredient: Mapped[list | None] = mapped_column(_JSONB, nullable=True)
    facet_values: Mapped[list | None] = mapped_column(_JSONB, nullable=True)
    facet_channel: Mapped[list | None] = mapped_column(_JSONB, nullable=True)
    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingredients.id", ondelete="SET NULL"), nullable=True
    )
    lifecycle: Mapped[str | None] = mapped_column(String(20), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("themes.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ThemeAlias(Base):
    __tablename__ = "theme_aliases"
    __table_args__ = (
        CheckConstraint(
            "alias_type IN ('synonym','abbreviation','misspelling','translation')",
            name="theme_aliases_type_check",
        ),
        Index("ix_theme_aliases_theme_id", "theme_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    theme_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("themes.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    alias_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="synonym")


class ThemeRelation(Base):
    __tablename__ = "theme_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_theme_id", "target_theme_id", "relation_type",
            name="uq_theme_relations_src_tgt_type",
        ),
        Index("ix_theme_relations_source", "source_theme_id"),
        Index("ix_theme_relations_target", "target_theme_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_theme_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("themes.id", ondelete="CASCADE"), nullable=False
    )
    target_theme_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("themes.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    strength: Mapped[float | None] = mapped_column(Float, nullable=True)
