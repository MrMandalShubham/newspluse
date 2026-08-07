"""Publisher — project product-related article_reports into the demo schema.

Maps each product article to a ``news_pulse_articles`` row (upsert by url) plus
brand/company/ingredient/product junctions and their lookup rows. Derived fields:
  * source_tier  <- source.trust_score band
  * market_id    <- source.region -> markets lookup
  * signal_tier  <- cluster size (1 = first-mention, 2-3 = emerging, >=4 = mainstream)
  * topic_velocity <- cluster size
  * reach        <- null (no audience data)
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from newspulse.db import SessionLocal
from newspulse.models import ArticleReport, RawItem, ReportCluster, Source
from newspulse.publish.models import (
    Brand,
    Company,
    Ingredient,
    Market,
    NewsArticleBrand,
    NewsArticleCompany,
    NewsArticleIngredient,
    NewsArticleProduct,
    NewsPulseArticle,
    ProductMaster,
)

# region code -> (market name, iso, flag)
MARKET_MAP = {
    "IN": ("India", "IN", "🇮🇳"),
    "ID": ("Indonesia", "ID", "🇮🇩"),
    "US": ("United States", "US", "🇺🇸"),
    "KR": ("South Korea", "KR", "🇰🇷"),
    "JP": ("Japan", "JP", "🇯🇵"),
    "GB": ("United Kingdom", "GB", "🇬🇧"),
    "CN": ("China", "CN", "🇨🇳"),
}


def _source_tier(trust: float | None) -> str:
    if trust is None:
        return "tier-3"
    if trust >= 0.7:
        return "tier-1"
    if trust >= 0.4:
        return "tier-2"
    return "tier-3"


def _signal_tier(size: int) -> str:
    if size >= 4:
        return "mainstream"
    if size >= 2:
        return "emerging-topic"
    return "first-mention"


def _unique(names: list[str] | None) -> list[str]:
    return list(dict.fromkeys(n.strip() for n in (names or []) if n and n.strip()))


def _get_or_create(session: Session, model, name: str):
    obj = session.execute(select(model).where(model.name == name)).scalar_one_or_none()
    if obj is None:
        obj = model(name=name)
        session.add(obj)
        session.flush()
    return obj


def _get_or_create_market(session: Session, region: str | None):
    if not region:
        return None
    name, iso, flag = MARKET_MAP.get(region, (region, region, None))
    market = session.execute(select(Market).where(Market.name == name)).scalar_one_or_none()
    if market is None:
        market = Market(name=name, iso_code=iso, flag=flag)
        session.add(market)
        session.flush()
    return market


_JUNCTIONS = (
    ("brands", Brand, NewsArticleBrand, "brand_id"),
    ("companies", Company, NewsArticleCompany, "company_id"),
    ("ingredients", Ingredient, NewsArticleIngredient, "ingredient_id"),
    ("products", ProductMaster, NewsArticleProduct, "product_id"),
)


def publish(session: Session | None = None) -> dict[str, int]:
    """Publish all product-related articles into the demo schema (idempotent)."""
    own_session = session is None
    session = session or SessionLocal()
    try:
        rows = session.execute(
            select(ArticleReport, RawItem, Source)
            .join(RawItem, RawItem.id == ArticleReport.raw_item_id)
            .join(Source, Source.id == RawItem.source_id)
            .where(ArticleReport.is_product_related.is_(True))
            .order_by(ArticleReport.id)
        ).all()

        published = 0
        for report, raw, source in rows:
            market = _get_or_create_market(session, source.region)
            size = 1
            if report.cluster_id is not None:
                cluster = session.get(ReportCluster, report.cluster_id)
                size = cluster.size if cluster else 1

            article = session.execute(
                select(NewsPulseArticle).where(NewsPulseArticle.url == raw.url)
            ).scalar_one_or_none()
            if article is None:
                article = NewsPulseArticle(url=raw.url)
                session.add(article)

            article.headline = report.title or raw.title or raw.url
            article.summary = report.summary
            article.source = source.name
            article.source_tier = _source_tier(source.trust_score)
            article.market_id = market.id if market else None
            article.category = report.category
            article.sentiment = report.sentiment
            article.theme = report.theme
            article.reach = None
            article.published_at = raw.published_at
            article.signal_tier = _signal_tier(size)
            article.topic_velocity = float(size)
            session.flush()

            # Rebuild junctions from the report's typed entity lists.
            for attr, lookup_model, junction_model, fk in _JUNCTIONS:
                session.execute(
                    delete(junction_model).where(junction_model.article_id == article.id)
                )
                for name in _unique(getattr(report, attr)):
                    entity = _get_or_create(session, lookup_model, name)
                    session.add(junction_model(article_id=article.id, **{fk: entity.id}))
            published += 1

        session.commit()
        return {"published": published}
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()
