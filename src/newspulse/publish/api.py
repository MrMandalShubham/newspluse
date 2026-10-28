"""News Pulse API — serves articles + leads from the platform DB (defaultdb).

Endpoints:
    GET  /api/news-pulse/articles          — paginated list, filterable
    GET  /api/news-pulse/articles/{slug}   — single article by slug
    GET  /api/news-pulse/brands            — all brands with article counts
    GET  /api/news-pulse/markets           — all markets with article counts
    POST /api/news-pulse/leads             — capture a new lead
    GET  /api/news-pulse/leads             — list leads (admin)
    GET  /api/news-pulse/leads/{id}        — single lead
    PATCH /api/news-pulse/leads/{id}       — update lead status
    POST /api/news-pulse/webhooks/lead-event  — Vercel frontend → Klaviyo sync
    POST /api/news-pulse/webhooks/klaviyo     — Klaviyo → DO status sync
"""

import hmac
import logging
import uuid
from collections.abc import Iterator
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from newspulse.config import settings
from newspulse.integrations import klaviyo as klaviyo_client

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news-pulse", tags=["news-pulse"])

_engine = None
_SessionFactory = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.publish_database_url, pool_pre_ping=True, future=True,
        )
    return _engine


def _get_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=_get_engine(), autoflush=False, expire_on_commit=False,
        )
    return _SessionFactory


def get_platform_session() -> Iterator[Session]:
    session = _get_session_factory()()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class BrandOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str | None = None
    article_count: int = 0


class MarketOut(BaseModel):
    code: str
    name: str
    article_count: int = 0


class EntityRef(BaseModel):
    id: uuid.UUID
    name: str
    slug: str | None = None


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str | None
    story_id: str | None = None
    headline: str
    summary: str | None
    source: str | None
    source_tier: str | None
    url: str
    image_url: str | None
    market: str | None = None
    market_code: str | None = None
    signal_tier: str | None
    topic_velocity: float | None
    importance_score: int | None
    event_types: list[str] | None
    published_at: datetime | None
    brands: list[EntityRef] = []
    products: list[EntityRef] = []
    companies: list[EntityRef] = []
    ingredients: list[EntityRef] = []


class ArticleListOut(BaseModel):
    articles: list[ArticleOut]
    total: int
    page: int
    page_size: int


class StorySourceOut(BaseModel):
    headline: str
    source: str | None
    url: str
    published_at: datetime | None


class StoryOut(BaseModel):
    story_id: str
    headline: str
    summary: str | None
    source_count: int
    signal_tier: str | None
    importance_score: int | None
    topic_velocity: float | None
    sources: list[StorySourceOut] = []
    brands: list[EntityRef] = []


class StoryListOut(BaseModel):
    stories: list[StoryOut]
    total: int
    page: int
    page_size: int


class TopicClusterOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    article_count: int
    source_count: int
    primary_country: str | None
    primary_category: str | None
    is_mixed_country: bool
    is_mixed_category: bool
    sentiment: str | None
    velocity: float | None


class TopicClusterDetailOut(TopicClusterOut):
    articles: list[ArticleOut] = []


class TopicClusterListOut(BaseModel):
    clusters: list[TopicClusterOut]
    total: int
    page: int
    page_size: int


VALID_LEAD_SOURCES = {
    "news-pulse", "newsletter", "contact-form",
    "agency-site", "download-report", "other",
}
VALID_LEAD_STATUSES = {
    "pending", "confirmed", "subscribed",
    "unsubscribed", "converted", "bounced",
}


class LeadCreateIn(BaseModel):
    email: str
    name: str | None = None
    company: str | None = None
    job_title: str | None = None
    country_interest: str | None = None
    source: str = "news-pulse"
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        import re
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("invalid email address")
        return v.lower().strip()


class LeadUpdateIn(BaseModel):
    status: str | None = None
    stripe_customer_id: str | None = None
    last_email_sent_at: datetime | None = None


class LeadOut(BaseModel):
    id: int
    email: str
    name: str | None
    company: str | None
    job_title: str | None
    country_interest: str | None
    source: str
    status: str
    stripe_customer_id: str | None
    email_tool_id: str | None
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    created_at: datetime
    confirmed_at: datetime | None
    unsubscribed_at: datetime | None
    last_email_sent_at: datetime | None


class LeadListOut(BaseModel):
    leads: list[LeadOut]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_article(row, session: Session) -> ArticleOut:
    """Build an ArticleOut from a raw SQL row, resolving linked entities."""
    return _build_articles_batch([row], session)[0]


def _build_articles_batch(rows, session: Session) -> list[ArticleOut]:
    """Build ArticleOut list with bulk entity loading (4 queries total)."""
    if not rows:
        return []

    aids = [r.id for r in rows]
    aid_str = ",".join(f"'{a}'" for a in aids)

    brands_map: dict = {}
    for b in session.execute(text(
        f"SELECT ab.article_id, b.id, b.name, b.slug FROM brands b "
        f"JOIN news_article_brands ab ON ab.brand_id = b.id "
        f"WHERE ab.article_id IN ({aid_str})"
    )).fetchall():
        brands_map.setdefault(b.article_id, []).append(
            EntityRef(id=b.id, name=b.name, slug=b.slug))

    products_map: dict = {}
    for p in session.execute(text(
        f"SELECT ap.article_id, p.id, p.name, p.slug FROM products_master p "
        f"JOIN news_article_products ap ON ap.product_id = p.id "
        f"WHERE ap.article_id IN ({aid_str})"
    )).fetchall():
        products_map.setdefault(p.article_id, []).append(
            EntityRef(id=p.id, name=p.name, slug=p.slug))

    companies_map: dict = {}
    for c in session.execute(text(
        f"SELECT ac.article_id, c.id, c.name, NULL as slug FROM companies c "
        f"JOIN news_article_companies ac ON ac.company_id = c.id "
        f"WHERE ac.article_id IN ({aid_str})"
    )).fetchall():
        companies_map.setdefault(c.article_id, []).append(
            EntityRef(id=c.id, name=c.name, slug=c.slug))

    ingredients_map: dict = {}
    for i in session.execute(text(
        f"SELECT ai.article_id, i.id, i.name, i.slug FROM ingredients i "
        f"JOIN news_article_ingredients ai ON ai.ingredient_id = i.id "
        f"WHERE ai.article_id IN ({aid_str})"
    )).fetchall():
        ingredients_map.setdefault(i.article_id, []).append(
            EntityRef(id=i.id, name=i.name, slug=i.slug))

    return [
        ArticleOut(
            id=row.id,
            slug=row.slug,
            story_id=getattr(row, "story_id", None),
            headline=row.headline,
            summary=row.summary,
            source=row.source,
            source_tier=row.source_tier,
            url=row.url,
            image_url=row.image_url,
            market=row.market_name,
            market_code=row.market_code,
            signal_tier=row.signal_tier,
            topic_velocity=row.topic_velocity,
            importance_score=row.importance_score,
            event_types=row.event_types,
            published_at=row.published_at,
            brands=brands_map.get(row.id, []),
            products=products_map.get(row.id, []),
            companies=companies_map.get(row.id, []),
            ingredients=ingredients_map.get(row.id, []),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class MarketCoverage(BaseModel):
    code: str
    name: str
    article_count: int
    percentage: float


class MonthlyCount(BaseModel):
    month: str
    count: int


class StatsOut(BaseModel):
    total_articles: int
    total_stories: int
    total_brands: int
    total_markets: int
    monthly_history: list[MonthlyCount]
    market_coverage: list[MarketCoverage]
    signal_breakdown: dict[str, int]
    avg_importance: float | None


@router.get("/stats", response_model=StatsOut)
def get_stats(
    session: Session = Depends(get_platform_session),
) -> StatsOut:
    total_articles = session.execute(
        text("SELECT count(*) FROM news_pulse_articles"),
    ).scalar() or 0

    total_stories = session.execute(
        text("SELECT count(DISTINCT story_id) FROM news_pulse_articles WHERE story_id IS NOT NULL"),
    ).scalar() or 0

    total_brands = session.execute(
        text("SELECT count(*) FROM brands"),
    ).scalar() or 0

    total_markets = session.execute(
        text("SELECT count(*) FROM markets"),
    ).scalar() or 0

    monthly_rows = session.execute(text(
        "SELECT to_char(date_trunc('month', published_at), 'YYYY-MM') as month, "
        "count(*) as cnt "
        "FROM news_pulse_articles "
        "WHERE published_at >= now() - interval '12 months' "
        "GROUP BY date_trunc('month', published_at) "
        "ORDER BY date_trunc('month', published_at)"
    )).fetchall()
    monthly_history = [MonthlyCount(month=r.month, count=r.cnt) for r in monthly_rows]

    market_rows = session.execute(text(
        "SELECT m.code, m.name, count(a.id) as cnt, "
        "round(count(a.id)::numeric / NULLIF(sum(count(a.id)) over(), 0) * 100, 1) as pct "
        "FROM news_pulse_articles a "
        "JOIN markets m ON a.market_id = m.id "
        "GROUP BY m.code, m.name "
        "ORDER BY cnt DESC"
    )).fetchall()
    market_coverage = [
        MarketCoverage(code=r.code, name=r.name, article_count=r.cnt, percentage=float(r.pct or 0))
        for r in market_rows
    ]

    signal_rows = session.execute(text(
        "SELECT signal_tier, count(*) as cnt "
        "FROM news_pulse_articles "
        "WHERE signal_tier IS NOT NULL "
        "GROUP BY signal_tier"
    )).fetchall()
    signal_breakdown = {r.signal_tier: r.cnt for r in signal_rows}

    avg_imp = session.execute(text(
        "SELECT round(avg(importance_score)::numeric, 1) FROM news_pulse_articles "
        "WHERE importance_score IS NOT NULL"
    )).scalar()

    return StatsOut(
        total_articles=total_articles,
        total_stories=total_stories,
        total_brands=total_brands,
        total_markets=total_markets,
        monthly_history=monthly_history,
        market_coverage=market_coverage,
        signal_breakdown=signal_breakdown,
        avg_importance=float(avg_imp) if avg_imp else None,
    )


@router.get("/articles", response_model=ArticleListOut)
def list_articles(
    brand: str | None = Query(None, description="Filter by brand slug"),
    market: str | None = Query(None, description="Filter by market code"),
    signal: str | None = Query(None, description="Filter by signal_tier"),
    event_type: str | None = Query(None, description="Filter by event type"),
    story: str | None = Query(None, description="Filter by story_id (group of related articles)"),
    q: str | None = Query(None, description="Search headline/summary"),
    sort: str = Query("recent", description="Sort: recent, importance, velocity"),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, description="Results per page; omit for all"),
    session: Session = Depends(get_platform_session),
) -> ArticleListOut:
    where_clauses = []
    params: dict = {}

    base = (
        "FROM news_pulse_articles a "
        "JOIN markets m ON a.market_id = m.id "
    )

    if brand:
        base += "JOIN news_article_brands ab ON ab.article_id = a.id "
        base += "JOIN brands b ON b.id = ab.brand_id "
        where_clauses.append("b.slug = :brand_slug")
        params["brand_slug"] = brand

    if market:
        where_clauses.append("m.code = :market_code")
        params["market_code"] = market.upper()

    if signal:
        where_clauses.append("a.signal_tier = :signal")
        params["signal"] = signal

    if event_type:
        where_clauses.append("a.event_types::jsonb @> :evt::jsonb")
        params["evt"] = f'["{event_type}"]'

    if story:
        where_clauses.append("a.story_id = :story_id")
        params["story_id"] = story

    if q:
        where_clauses.append("(a.headline ILIKE :q OR a.summary ILIKE :q)")
        escaped_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params["q"] = f"%{escaped_q}%"

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    order = {
        "recent": "a.published_at DESC NULLS LAST",
        "importance": "a.importance_score DESC NULLS LAST, a.published_at DESC NULLS LAST",
        "velocity": "a.topic_velocity DESC NULLS LAST, a.published_at DESC NULLS LAST",
    }.get(sort, "a.published_at DESC NULLS LAST")

    total = session.execute(
        text(f"SELECT count(DISTINCT a.id) {base}{where_sql}"), params,
    ).scalar()

    if page_size is None:
        rows = session.execute(text(
            f"SELECT a.*, m.name as market_name, m.code as market_code "
            f"{base} {where_sql} "
            f"GROUP BY a.id, m.name, m.code "
            f"ORDER BY {order}"
        ), params).fetchall()
    else:
        offset = (page - 1) * page_size
        rows = session.execute(text(
            f"SELECT a.*, m.name as market_name, m.code as market_code "
            f"{base} {where_sql} "
            f"GROUP BY a.id, m.name, m.code "
            f"ORDER BY {order} LIMIT :lim OFFSET :off"
        ), {**params, "lim": page_size, "off": offset}).fetchall()

    articles = _build_articles_batch(rows, session)
    actual_page_size = page_size or total

    return ArticleListOut(articles=articles, total=total, page=page, page_size=actual_page_size)


@router.get("/articles/{slug}", response_model=ArticleOut)
def get_article(slug: str, session: Session = Depends(get_platform_session)) -> ArticleOut:
    row = session.execute(text(
        "SELECT a.*, m.name as market_name, m.code as market_code "
        "FROM news_pulse_articles a "
        "JOIN markets m ON a.market_id = m.id "
        "WHERE a.slug = :slug"
    ), {"slug": slug}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="article not found")
    return _build_article(row, session)


@router.get("/brands", response_model=list[BrandOut])
def list_brands(
    min_articles: int = Query(0, ge=0, description="Minimum article count to include"),
    session: Session = Depends(get_platform_session),
) -> list[BrandOut]:
    rows = session.execute(text(
        "SELECT b.id, b.name, b.slug, count(ab.article_id) as cnt "
        "FROM brands b "
        "JOIN news_article_brands ab ON ab.brand_id = b.id "
        "GROUP BY b.id, b.name, b.slug "
        "HAVING count(ab.article_id) >= :min "
        "ORDER BY cnt DESC"
    ), {"min": min_articles}).fetchall()
    return [BrandOut(id=r.id, name=r.name, slug=r.slug, article_count=r.cnt) for r in rows]


@router.get("/markets", response_model=list[MarketOut])
def list_markets(
    session: Session = Depends(get_platform_session),
) -> list[MarketOut]:
    rows = session.execute(text(
        "SELECT m.code, m.name, count(a.id) as cnt "
        "FROM markets m "
        "JOIN news_pulse_articles a ON a.market_id = m.id "
        "GROUP BY m.code, m.name "
        "ORDER BY cnt DESC"
    )).fetchall()
    return [MarketOut(code=r.code, name=r.name, article_count=r.cnt) for r in rows]


@router.get("/stories", response_model=StoryListOut)
def list_stories(
    brand: str | None = Query(None, description="Filter by brand slug"),
    market: str | None = Query(None, description="Filter by market code"),
    min_sources: int = Query(1, ge=1, description="Minimum source count"),
    sort: str = Query("importance", description="Sort: importance, velocity, recent, sources"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_platform_session),
) -> StoryListOut:
    joins = ""
    where_clauses = ["a.story_id IS NOT NULL"]
    params: dict = {}

    if brand:
        joins += ("JOIN news_article_brands ab ON ab.article_id = a.id "
                  "JOIN brands b ON b.id = ab.brand_id ")
        where_clauses.append("b.slug = :brand_slug")
        params["brand_slug"] = brand

    if market:
        where_clauses.append("m.code = :market_code")
        params["market_code"] = market.upper()

    where_sql = " WHERE " + " AND ".join(where_clauses)

    order = {
        "importance": "max_importance DESC, source_count DESC",
        "velocity": "source_count DESC, max_importance DESC",
        "recent": "latest_published DESC",
        "sources": "source_count DESC, max_importance DESC",
    }.get(sort, "max_importance DESC, source_count DESC")

    count_q = (
        f"SELECT count(*) FROM ("
        f"  SELECT a.story_id FROM news_pulse_articles a "
        f"  JOIN markets m ON a.market_id = m.id {joins}{where_sql} "
        f"  GROUP BY a.story_id HAVING count(*) >= :min_src"
        f") sub"
    )
    total = session.execute(text(count_q), {**params, "min_src": min_sources}).scalar()

    offset = (page - 1) * page_size
    story_rows = session.execute(text(
        f"SELECT a.story_id, "
        f"  max(a.headline) as headline, max(a.summary) as summary, "
        f"  count(*) as source_count, "
        f"  max(a.signal_tier) as signal_tier, "
        f"  max(a.importance_score) as max_importance, "
        f"  max(a.topic_velocity) as topic_velocity, "
        f"  max(a.published_at) as latest_published "
        f"FROM news_pulse_articles a "
        f"JOIN markets m ON a.market_id = m.id {joins}{where_sql} "
        f"GROUP BY a.story_id "
        f"HAVING count(*) >= :min_src "
        f"ORDER BY {order} LIMIT :lim OFFSET :off"
    ), {**params, "min_src": min_sources, "lim": page_size, "off": offset}).fetchall()

    stories = []
    for sr in story_rows:
        sources = session.execute(text(
            "SELECT headline, source, url, published_at "
            "FROM news_pulse_articles WHERE story_id = :sid "
            "ORDER BY published_at ASC"
        ), {"sid": sr.story_id}).fetchall()

        brand_rows = session.execute(text(
            "SELECT DISTINCT b.id, b.name, b.slug "
            "FROM brands b "
            "JOIN news_article_brands ab ON ab.brand_id = b.id "
            "JOIN news_pulse_articles a ON a.id = ab.article_id "
            "WHERE a.story_id = :sid"
        ), {"sid": sr.story_id}).fetchall()

        stories.append(StoryOut(
            story_id=sr.story_id,
            headline=sr.headline,
            summary=sr.summary,
            source_count=sr.source_count,
            signal_tier=sr.signal_tier,
            importance_score=sr.max_importance,
            topic_velocity=sr.topic_velocity,
            sources=[StorySourceOut(
                headline=s.headline, source=s.source, url=s.url, published_at=s.published_at,
            ) for s in sources],
            brands=[EntityRef(id=b.id, name=b.name, slug=b.slug) for b in brand_rows],
        ))

    return StoryListOut(stories=stories, total=total, page=page, page_size=page_size)


@router.get("/stories/{story_id}", response_model=StoryOut)
def get_story(story_id: str, session: Session = Depends(get_platform_session)) -> StoryOut:
    articles = session.execute(text(
        "SELECT headline, summary, source, url, published_at, signal_tier, "
        "importance_score, topic_velocity "
        "FROM news_pulse_articles WHERE story_id = :sid "
        "ORDER BY published_at ASC"
    ), {"sid": story_id}).fetchall()
    if not articles:
        raise HTTPException(status_code=404, detail="story not found")

    brand_rows = session.execute(text(
        "SELECT DISTINCT b.id, b.name, b.slug "
        "FROM brands b "
        "JOIN news_article_brands ab ON ab.brand_id = b.id "
        "JOIN news_pulse_articles a ON a.id = ab.article_id "
        "WHERE a.story_id = :sid"
    ), {"sid": story_id}).fetchall()

    best = max(articles, key=lambda a: a.importance_score or 0)
    return StoryOut(
        story_id=story_id,
        headline=best.headline,
        summary=best.summary,
        source_count=len(articles),
        signal_tier=best.signal_tier,
        importance_score=best.importance_score,
        topic_velocity=best.topic_velocity,
        sources=[StorySourceOut(
            headline=a.headline, source=a.source, url=a.url, published_at=a.published_at,
        ) for a in articles],
        brands=[EntityRef(id=b.id, name=b.name, slug=b.slug) for b in brand_rows],
    )


@router.get("/topics", response_model=TopicClusterListOut)
def list_topics(
    country: str | None = Query(None, description="Filter by primary_country code"),
    category: str | None = Query(None, description="Filter by primary_category"),
    min_articles: int = Query(2, ge=1, description="Minimum article count"),
    sort: str = Query("velocity", description="Sort: velocity, articles, recent"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_platform_session),
) -> TopicClusterListOut:
    where_clauses = ["tc.article_count >= :min_art"]
    params: dict = {"min_art": min_articles}

    if country:
        where_clauses.append("tc.primary_country = :country")
        params["country"] = country.upper()

    if category:
        where_clauses.append("tc.primary_category = :category")
        params["category"] = category

    where_sql = " WHERE " + " AND ".join(where_clauses)

    order = {
        "velocity": "tc.velocity DESC NULLS LAST",
        "articles": "tc.article_count DESC",
        "recent": "tc.updated_at DESC",
    }.get(sort, "tc.velocity DESC NULLS LAST")

    total = session.execute(
        text(f"SELECT count(*) FROM topic_clusters tc{where_sql}"), params,
    ).scalar()

    offset = (page - 1) * page_size
    rows = session.execute(text(
        f"SELECT * FROM topic_clusters tc{where_sql} "
        f"ORDER BY {order} LIMIT :lim OFFSET :off"
    ), {**params, "lim": page_size, "off": offset}).fetchall()

    clusters = [TopicClusterOut(
        id=r.id, name=r.name, slug=r.slug, description=r.description,
        article_count=r.article_count, source_count=r.source_count,
        primary_country=r.primary_country, primary_category=r.primary_category,
        is_mixed_country=r.is_mixed_country, is_mixed_category=r.is_mixed_category,
        sentiment=r.sentiment, velocity=r.velocity,
    ) for r in rows]

    return TopicClusterListOut(clusters=clusters, total=total, page=page, page_size=page_size)


@router.get("/topics/{slug}", response_model=TopicClusterDetailOut)
def get_topic(slug: str, session: Session = Depends(get_platform_session)) -> TopicClusterDetailOut:
    tc = session.execute(text(
        "SELECT * FROM topic_clusters WHERE slug = :slug"
    ), {"slug": slug}).fetchone()
    if not tc:
        raise HTTPException(status_code=404, detail="topic cluster not found")

    article_rows = session.execute(text(
        "SELECT a.*, m.name as market_name, m.code as market_code "
        "FROM news_pulse_articles a "
        "JOIN markets m ON a.market_id = m.id "
        "JOIN topic_cluster_members tcm ON tcm.article_id = a.id "
        "WHERE tcm.cluster_id = :cid "
        "ORDER BY a.importance_score DESC NULLS LAST, a.published_at DESC NULLS LAST"
    ), {"cid": tc.id}).fetchall()

    articles = _build_articles_batch(article_rows, session)

    return TopicClusterDetailOut(
        id=tc.id, name=tc.name, slug=tc.slug, description=tc.description,
        article_count=tc.article_count, source_count=tc.source_count,
        primary_country=tc.primary_country, primary_category=tc.primary_category,
        is_mixed_country=tc.is_mixed_country, is_mixed_category=tc.is_mixed_category,
        sentiment=tc.sentiment, velocity=tc.velocity,
        articles=articles,
    )


# ---------------------------------------------------------------------------
# Leads endpoints
# ---------------------------------------------------------------------------

def _row_to_lead(row) -> LeadOut:
    return LeadOut(
        id=row.id, email=row.email, name=row.name, company=row.company,
        job_title=row.job_title, country_interest=row.country_interest,
        source=row.source, status=row.status,
        stripe_customer_id=row.stripe_customer_id,
        email_tool_id=getattr(row, "email_tool_id", None),
        utm_source=row.utm_source, utm_medium=row.utm_medium,
        utm_campaign=row.utm_campaign, created_at=row.created_at,
        confirmed_at=row.confirmed_at, unsubscribed_at=row.unsubscribed_at,
        last_email_sent_at=row.last_email_sent_at,
    )


async def _sync_lead_to_klaviyo(
    email: str,
    name: str | None,
    company: str | None,
    job_title: str | None,
    country: str | None,
    source: str | None,
    utm_source: str | None,
    utm_medium: str | None,
    utm_campaign: str | None,
) -> None:
    try:
        profile_id = await klaviyo_client.upsert_profile(
            email,
            name=name,
            company=company,
            job_title=job_title,
            country=country,
            source=source,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_campaign=utm_campaign,
        )
        if profile_id:
            await klaviyo_client.subscribe_to_list(profile_id)
            _store_email_tool_id(email, profile_id)
    except Exception:
        log.exception("klaviyo: failed to sync new lead %s", email)


def _store_email_tool_id(email: str, profile_id: str) -> None:
    """Persist the Klaviyo profile ID in leads.email_tool_id."""
    try:
        engine = _get_engine()
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE leads SET email_tool_id = :pid WHERE email = :email"),
                {"pid": profile_id, "email": email},
            )
    except Exception:
        log.exception("failed to store email_tool_id for %s", email)


@router.post("/leads", response_model=LeadOut, status_code=201)
def create_lead(
    body: LeadCreateIn,
    session: Session = Depends(get_platform_session),
) -> LeadOut:
    if body.source not in VALID_LEAD_SOURCES:
        raise HTTPException(400, f"invalid source; must be one of {VALID_LEAD_SOURCES}")

    existing = session.execute(
        text("SELECT id FROM leads WHERE email = :email"),
        {"email": body.email},
    ).fetchone()
    if existing:
        raise HTTPException(409, "email already registered")

    row = session.execute(text(
        "INSERT INTO leads (email, name, company, job_title, country_interest, "
        "source, status, utm_source, utm_medium, utm_campaign) "
        "VALUES (:email, :name, :company, :job_title, :country_interest, "
        ":source, 'pending', :utm_source, :utm_medium, :utm_campaign) "
        "RETURNING *"
    ), {
        "email": body.email, "name": body.name, "company": body.company,
        "job_title": body.job_title, "country_interest": body.country_interest,
        "source": body.source, "utm_source": body.utm_source,
        "utm_medium": body.utm_medium, "utm_campaign": body.utm_campaign,
    }).fetchone()
    session.commit()

    return _row_to_lead(row)


@router.get("/leads", response_model=LeadListOut)
def list_leads(
    status: str | None = Query(None, description="Filter by status"),
    source: str | None = Query(None, description="Filter by source"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_platform_session),
) -> LeadListOut:
    where_clauses: list[str] = []
    params: dict = {}

    if status:
        where_clauses.append("status = :status")
        params["status"] = status
    if source:
        where_clauses.append("source = :source")
        params["source"] = source

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    total = session.execute(
        text(f"SELECT count(*) FROM leads{where_sql}"), params,
    ).scalar()

    offset = (page - 1) * page_size
    rows = session.execute(text(
        f"SELECT * FROM leads{where_sql} "
        f"ORDER BY created_at DESC LIMIT :lim OFFSET :off"
    ), {**params, "lim": page_size, "off": offset}).fetchall()

    return LeadListOut(
        leads=[_row_to_lead(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@router.get("/leads/{lead_id}", response_model=LeadOut)
def get_lead(
    lead_id: int,
    session: Session = Depends(get_platform_session),
) -> LeadOut:
    row = session.execute(
        text("SELECT * FROM leads WHERE id = :id"), {"id": lead_id},
    ).fetchone()
    if not row:
        raise HTTPException(404, "lead not found")
    return _row_to_lead(row)


async def _sync_status_to_klaviyo(
    email: str, new_status: str, email_tool_id: str | None = None,
) -> None:
    try:
        profile_id = email_tool_id or await klaviyo_client.get_profile_by_email(email)
        if not profile_id:
            return
        if new_status == "unsubscribed":
            await klaviyo_client.suppress_profile(profile_id)
        await klaviyo_client.track_event(
            profile_id,
            "Lead Status Changed",
            {"new_status": new_status},
        )
    except Exception:
        log.exception("klaviyo: failed to sync status for %s", email)


@router.patch("/leads/{lead_id}", response_model=LeadOut)
def update_lead(
    lead_id: int,
    body: LeadUpdateIn,
    bg: BackgroundTasks,
    session: Session = Depends(get_platform_session),
) -> LeadOut:
    sets: list[str] = []
    params: dict = {"id": lead_id}

    if body.status is not None:
        if body.status not in VALID_LEAD_STATUSES:
            raise HTTPException(400, f"invalid status; must be one of {VALID_LEAD_STATUSES}")
        sets.append("status = :status")
        params["status"] = body.status
        if body.status == "confirmed":
            sets.append("confirmed_at = now()")
        elif body.status == "unsubscribed":
            sets.append("unsubscribed_at = now()")

    if body.stripe_customer_id is not None:
        sets.append("stripe_customer_id = :stripe_id")
        params["stripe_id"] = body.stripe_customer_id

    if body.last_email_sent_at is not None:
        sets.append("last_email_sent_at = :last_sent")
        params["last_sent"] = body.last_email_sent_at

    if not sets:
        raise HTTPException(400, "no fields to update")

    row = session.execute(text(
        f"UPDATE leads SET {', '.join(sets)} WHERE id = :id RETURNING *"
    ), params).fetchone()
    if not row:
        raise HTTPException(404, "lead not found")
    session.commit()

    if body.status is not None:
        bg.add_task(
            _sync_status_to_klaviyo, row.email, body.status,
            getattr(row, "email_tool_id", None),
        )

    return _row_to_lead(row)


# ---------------------------------------------------------------------------
# Klaviyo webhook — receives unsubscribe/subscribe events
# ---------------------------------------------------------------------------

_KLAVIYO_EVENT_TO_STATUS = {
    "unsubscribed": "unsubscribed",
    "subscribed": "subscribed",
    "marked_as_spam": "unsubscribed",
}


@router.post("/webhooks/klaviyo", status_code=200)
async def klaviyo_webhook(request: Request) -> dict:
    """Handle Klaviyo webhook events (unsubscribe, subscribe, spam)."""
    secret = settings.klaviyo_webhook_secret
    if secret:
        header_secret = request.headers.get("x-klaviyo-webhook-secret", "")
        if not hmac.compare_digest(secret, header_secret):
            raise HTTPException(401, "invalid webhook secret")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON body") from None

    event_type = (payload.get("type") or payload.get("event") or "").lower()
    email = None
    profile_id = None

    data = payload.get("data", {})
    attrs = data.get("attributes", {}) if isinstance(data, dict) else {}
    profile_data = attrs.get("profile", {}).get("data", {})
    if isinstance(profile_data, dict):
        profile_attrs = profile_data.get("attributes", {})
        email = profile_attrs.get("email")
        profile_id = profile_data.get("id")

    if not email:
        email = (
            attrs.get("email")
            or payload.get("email")
            or (data if isinstance(data, dict) else {}).get("email")
        )
    if not profile_id:
        profile_id = (
            attrs.get("profile_id")
            or payload.get("profile_id")
            or (data if isinstance(data, dict) else {}).get("id")
        )

    if not email and not profile_id:
        log.warning("klaviyo webhook: no email or profile_id in payload")
        return {"status": "ignored", "reason": "no identifiers"}

    new_status = _KLAVIYO_EVENT_TO_STATUS.get(event_type)
    if not new_status:
        log.info("klaviyo webhook: ignoring event type '%s'", event_type)
        return {"status": "ignored", "reason": f"unhandled event: {event_type}"}

    engine = _get_engine()
    with engine.begin() as conn:
        if email:
            row = conn.execute(
                text("SELECT id, status FROM leads WHERE email = :e"), {"e": email},
            ).first()
        elif profile_id:
            row = conn.execute(
                text("SELECT id, status FROM leads WHERE email_tool_id = :pid"),
                {"pid": profile_id},
            ).first()
        else:
            row = None

        if not row:
            log.info("klaviyo webhook: lead not found for %s", email or profile_id)
            return {"status": "ignored", "reason": "lead not found"}

        if row.status == new_status:
            return {"status": "ok", "detail": "already up to date"}

        sets = ["status = :status"]
        params: dict = {"status": new_status, "lid": row.id}
        if new_status == "unsubscribed":
            sets.append("unsubscribed_at = now()")

        conn.execute(
            text(f"UPDATE leads SET {', '.join(sets)} WHERE id = :lid"), params,
        )

    log.info(
        "klaviyo webhook: updated lead %s -> %s (event=%s)",
        row.id, new_status, event_type,
    )
    return {"status": "ok", "lead_id": row.id, "new_status": new_status}


# ---------------------------------------------------------------------------
# Lead-event webhook — replaces N8N_WEBHOOK_URL for Vercel frontend
# ---------------------------------------------------------------------------

class LeadEventIn(BaseModel):
    lead_id: int | None = None
    email: str | None = None
    event: str


@router.post("/webhooks/lead-event", status_code=200)
async def lead_event_webhook(body: LeadEventIn) -> dict:
    """Handle lead lifecycle events from the Vercel frontend.

    Replaces N8N_WEBHOOK_URL. The frontend calls this after a lead
    confirms their email, unsubscribes, etc.

    Accepts: { lead_id?: int, email?: str, event: "confirmed"|"unsubscribed" }
    """
    if not body.lead_id and not body.email:
        raise HTTPException(400, "provide lead_id or email")

    engine = _get_engine()
    with engine.connect() as conn:
        if body.lead_id:
            row = conn.execute(
                text("SELECT * FROM leads WHERE id = :id"), {"id": body.lead_id},
            ).first()
        else:
            row = conn.execute(
                text("SELECT * FROM leads WHERE email = :e"), {"e": body.email},
            ).first()

    if not row:
        raise HTTPException(404, "lead not found")

    event = body.event.lower()

    if event == "confirmed":
        profile_id = await klaviyo_client.upsert_profile(
            row.email,
            name=row.name,
            company=row.company,
            job_title=row.job_title,
            country=row.country_interest,
            source=row.source,
            utm_source=row.utm_source,
            utm_medium=row.utm_medium,
            utm_campaign=row.utm_campaign,
        )
        if profile_id:
            await klaviyo_client.subscribe_to_list(profile_id)
            _store_email_tool_id(row.email, profile_id)
            await klaviyo_client.track_event(
                profile_id, "Lead Confirmed", {"source": row.source},
            )

        log.info("lead-event: confirmed lead %s, klaviyo profile %s", row.id, profile_id)
        return {"status": "ok", "lead_id": row.id, "klaviyo_profile_id": profile_id}

    if event == "unsubscribed":
        email_tool_id = getattr(row, "email_tool_id", None)
        profile_id = email_tool_id or await klaviyo_client.get_profile_by_email(row.email)
        if profile_id:
            await klaviyo_client.suppress_profile(profile_id)

        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE leads SET status = 'unsubscribed', "
                    "unsubscribed_at = now() WHERE id = :id"
                ),
                {"id": row.id},
            )

        log.info("lead-event: unsubscribed lead %s", row.id)
        return {"status": "ok", "lead_id": row.id, "new_status": "unsubscribed"}

    log.info("lead-event: ignoring event '%s' for lead %s", event, row.id)
    return {"status": "ignored", "reason": f"unhandled event: {event}"}
