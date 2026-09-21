"""Publish News Pulse output into the AsiaCosmePulse platform DB (defaultdb).

Two databases: reads article_reports from the working DB (``database_url``) and
writes the demo tables into the platform DB (``publish_database_url``). It
creates ONLY the missing tables (news_pulse_articles + 4 junctions + companies +
ingredients) and links to the platform's existing markets/brands/products_master
by name, creating catalog rows for unmatched entities (tagged data_source).
Existing tables are never dropped or altered.
"""

import json
import re
import uuid

from sqlalchemy import create_engine, select, text

from newspulse.config import settings
from newspulse.db import Base, SessionLocal
from newspulse.models import ArticleReport, RawItem, ReportCluster, Source
from newspulse.publish.models import (
    Company,
    Ingredient,
    NewsArticleBrand,
    NewsArticleCompany,
    NewsArticleIngredient,
    NewsArticleProduct,
    NewsPulseArticle,
)

# Only these tables are created in the platform DB (existing ones are reused).
NEW_TABLES = [
    Company.__table__,
    Ingredient.__table__,
    NewsPulseArticle.__table__,
    NewsArticleBrand.__table__,
    NewsArticleCompany.__table__,
    NewsArticleIngredient.__table__,
    NewsArticleProduct.__table__,
]

MARKET_MAP = {
    "IN": ("India", "IN", "🇮🇳"),
    "ID": ("Indonesia", "ID", "🇮🇩"),
    "US": ("United States", "US", "🇺🇸"),
    "KR": ("South Korea", "KR", "🇰🇷"),
    "JP": ("Japan", "JP", "🇯🇵"),
    "GB": ("United Kingdom", "GB", "🇬🇧"),
    "CN": ("China", "CN", "🇨🇳"),
    "HK": ("Hong Kong", "HK", "🇭🇰"),
}

_JUNCTIONS = ("news_article_brands", "news_article_companies",
              "news_article_ingredients", "news_article_products")

# LLM-extracted country name -> our region code (falls back to source region).
COUNTRY_TO_REGION = {
    "south korea": "KR", "korea": "KR", "republic of korea": "KR",
    "china": "CN", "mainland china": "CN", "prc": "CN",
    "japan": "JP",
    "hong kong": "HK", "hong kong sar": "HK",
    "india": "IN",
    "indonesia": "ID",
    "united states": "US", "usa": "US", "u.s.": "US",
    "united states of america": "US", "america": "US",
    "united kingdom": "GB", "uk": "GB", "u.k.": "GB", "britain": "GB", "england": "GB",
}


def _country_to_region(country: str | None) -> str | None:
    if not country:
        return None
    return COUNTRY_TO_REGION.get(country.strip().lower())


def _hybrid_importance(llm: int | None, size: int) -> int:
    """Blend LLM impact (1-10) with cross-source corroboration (cluster size)."""
    llm_score = llm if llm else 5
    corroboration = min(10, 5 + 2 * (size - 1))  # 1->5, 2->7, 3->9, 4+->10
    return max(1, min(10, round(0.6 * llm_score + 0.4 * corroboration)))


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] or "x"


def article_slug(headline: str | None, article_id: uuid.UUID) -> str:
    """Stable, permanent SEO slug: {headline}-{id6}. CJK/empty -> article-{id6}."""
    id6 = article_id.hex[:6]
    base = re.sub(r"[^a-z0-9]+", "-", (headline or "").lower()).strip("-")[:80]
    return f"{base}-{id6}" if base else f"article-{id6}"


def _source_tier(trust: float | None) -> str:
    if trust is None:
        return "tier-3"
    return "tier-1" if trust >= 0.7 else "tier-2" if trust >= 0.4 else "tier-3"


def _signal_tier(size: int) -> str:
    return "mainstream" if size >= 4 else "emerging-topic" if size >= 2 else "first-mention"


def _unique(names: list[str] | None) -> list[str]:
    return list(dict.fromkeys(n.strip() for n in (names or []) if n and n.strip()))


def _market_id(conn, region, stats):
    if not region:
        return None
    name, code, flag = MARKET_MAP.get(region, (region, region, None))
    row = conn.execute(text("select id from markets where code=:c"), {"c": code}).first()
    if row:
        return row[0]
    mid = uuid.uuid4()
    conn.execute(
        text("insert into markets(id,name,code,region,flag,created_at) "
             "values(:id,:n,:c,:r,:f, now())"),
        {"id": mid, "n": name, "c": code, "r": region, "f": flag},
    )
    stats["markets_new"] += 1
    return mid


def _brand_id(conn, name, stats):
    row = conn.execute(
        text("select id from brands where lower(name)=lower(:n)"), {"n": name}
    ).first()
    if row:
        stats["brands_matched"] += 1
        return row[0]
    bid = uuid.uuid4()
    conn.execute(
        text("insert into brands(id,code,name,created_at) values(:id,:c,:n, now())"),
        {"id": bid, "c": f"{_slug(name)}-{bid.hex[:6]}", "n": name},
    )
    stats["brands_new"] += 1
    return bid


def _product_id(conn, name, stats):
    row = conn.execute(
        text("select id from products_master where lower(name)=lower(:n)"), {"n": name}
    ).first()
    if row:
        stats["products_matched"] += 1
        return row[0]
    pid = uuid.uuid4()
    conn.execute(
        text("insert into products_master(id,name,data_source,created_at,updated_at) "
             "values(:id,:n,'newspulse', now(), now())"),
        {"id": pid, "n": name},
    )
    stats["products_new"] += 1
    return pid


def _lookup_id(conn, table, name):
    row = conn.execute(
        text(f"select id from {table} where lower(name)=lower(:n)"), {"n": name}
    ).first()
    if row:
        return row[0]
    eid = uuid.uuid4()
    conn.execute(
        text(f"insert into {table}(id,name,created_at) values(:id,:n, now())"),
        {"id": eid, "n": name},
    )
    return eid


def _upsert_article(conn, d, market_id):
    fields = {
        "headline": d["headline"], "summary": d["summary"], "source": d["source"],
        "source_tier": d["source_tier"], "market_id": market_id, "category": d["category"],
        "sentiment": d["sentiment"], "theme": d["theme"], "reach": None,
        "image_url": d.get("image_url"),
        "published_at": d["published_at"], "signal_tier": d["signal_tier"],
        "topic_velocity": d["topic_velocity"],
        "importance_score": d["importance_score"],
        "event_types": json.dumps(d["event_types"] or []),
    }
    row = conn.execute(
        text("select id from news_pulse_articles where url=:u"), {"u": d["url"]}
    ).first()
    if row:
        aid = row[0]
        conn.execute(
            text("update news_pulse_articles set headline=:headline, summary=:summary, "
                 "source=:source, source_tier=:source_tier, market_id=:market_id, "
                 "category=:category, sentiment=:sentiment, theme=:theme, reach=:reach, "
                 "image_url=:image_url, published_at=:published_at, signal_tier=:signal_tier, "
                 "topic_velocity=:topic_velocity, importance_score=:importance_score, "
                 "event_types=cast(:event_types as jsonb) where id=:id"),
            {**fields, "id": aid},
        )
    else:
        aid = uuid.uuid4()
        conn.execute(
            text("insert into news_pulse_articles(id,slug,url,headline,summary,source,"
                 "source_tier,market_id,category,sentiment,theme,reach,image_url,published_at,"
                 "signal_tier,topic_velocity,importance_score,event_types,created_at) values("
                 ":id,:slug,:url,:headline,:summary,:source,:source_tier,:market_id,:category,"
                 ":sentiment,:theme,:reach,:image_url,:published_at,:signal_tier,:topic_velocity,"
                 ":importance_score,cast(:event_types as jsonb), now())"),
            {**fields, "id": aid, "url": d["url"], "slug": article_slug(d["headline"], aid)},
        )
    for tbl in _JUNCTIONS:
        conn.execute(text(f"delete from {tbl} where article_id=:a"), {"a": aid})
    return aid


def _link(conn, table, col, aid, eid):
    conn.execute(
        text(f"insert into {table}(article_id,{col}) values(:a,:e) on conflict do nothing"),
        {"a": aid, "e": eid},
    )


def _collect_rows() -> list[dict]:
    work = SessionLocal()
    try:
        rows = work.execute(
            select(ArticleReport, RawItem, Source)
            .join(RawItem, RawItem.id == ArticleReport.raw_item_id)
            .join(Source, Source.id == RawItem.source_id)
            .where(ArticleReport.is_product_related.is_(True))
            .order_by(ArticleReport.id)
        ).all()
        out = []
        for ar, ri, src in rows:
            size = 1
            if ar.cluster_id is not None:
                cluster = work.get(ReportCluster, ar.cluster_id)
                size = cluster.size if cluster else 1
            out.append({
                "url": ri.url, "headline": ar.title or ri.title or ri.url,
                "image_url": ri.image_url,
                "summary": ar.summary, "source": src.name,
                "source_tier": _source_tier(src.trust_score),
                "region": _country_to_region(ar.country) or src.region,
                "category": ar.category, "sentiment": ar.sentiment, "theme": ar.theme,
                "event_types": ar.event_types,
                "importance_score": _hybrid_importance(ar.importance_score, size),
                "published_at": ri.published_at, "signal_tier": _signal_tier(size),
                "topic_velocity": float(size), "brands": ar.brands, "companies": ar.companies,
                "ingredients": ar.ingredients, "products": ar.products,
            })
        return out
    finally:
        work.close()


_BRAND_COUNT_VIEW = (
    "CREATE OR REPLACE VIEW news_pulse_brand_counts AS "
    "SELECT b.id AS brand_id, b.name, count(nab.article_id) AS article_count "
    "FROM brands b JOIN news_article_brands nab ON nab.brand_id = b.id "
    "GROUP BY b.id, b.name"
)


def _finalize(conn) -> dict:
    """Idempotent post-publish: backfill missing slugs + (re)create brand-count view."""
    rows = conn.execute(
        text("select id, headline from news_pulse_articles where slug is null")
    ).all()
    for r in rows:
        conn.execute(
            text("update news_pulse_articles set slug=:s where id=:id"),
            {"s": article_slug(r.headline, r.id), "id": r.id},
        )
    conn.execute(text(_BRAND_COUNT_VIEW))
    return {"slugs_backfilled": len(rows)}


def finalize_platform() -> dict:
    """Standalone: ensure slug column/index, backfill slugs, create brand-count view.

    Runs the additive DDL + _finalize without re-publishing every article — used to
    apply slug/view changes to an already-populated platform DB quickly.
    """
    plat = create_engine(settings.publish_database_url)
    try:
        with plat.begin() as conn:
            conn.execute(
                text("ALTER TABLE news_pulse_articles ADD COLUMN IF NOT EXISTS slug TEXT")
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_news_pulse_articles_slug "
                     "ON news_pulse_articles(slug)")
            )
            return _finalize(conn)
    finally:
        plat.dispose()


def publish_to_platform() -> dict:
    plat = create_engine(settings.publish_database_url)
    Base.metadata.create_all(plat, tables=NEW_TABLES, checkfirst=True)
    # Additive columns on our own table (safe, idempotent).
    with plat.begin() as conn:
        conn.execute(
            text("ALTER TABLE news_pulse_articles ADD COLUMN IF NOT EXISTS image_url TEXT")
        )
        conn.execute(
            text("ALTER TABLE news_pulse_articles "
                 "ADD COLUMN IF NOT EXISTS importance_score INTEGER")
        )
        conn.execute(
            text("ALTER TABLE news_pulse_articles "
                 "ADD COLUMN IF NOT EXISTS event_types JSONB")
        )
        conn.execute(
            text("ALTER TABLE news_pulse_articles ADD COLUMN IF NOT EXISTS slug TEXT")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_news_pulse_articles_slug "
                 "ON news_pulse_articles(slug)")
        )
    data = _collect_rows()
    stats = {"articles": 0, "brands_matched": 0, "brands_new": 0,
             "products_matched": 0, "products_new": 0, "markets_new": 0}
    try:
        with plat.begin() as conn:
            for d in data:
                market_id = _market_id(conn, d["region"], stats)
                aid = _upsert_article(conn, d, market_id)
                for name in _unique(d["brands"]):
                    _link(conn, "news_article_brands", "brand_id", aid,
                          _brand_id(conn, name, stats))
                for name in _unique(d["companies"]):
                    _link(conn, "news_article_companies", "company_id", aid,
                          _lookup_id(conn, "companies", name))
                for name in _unique(d["ingredients"]):
                    _link(conn, "news_article_ingredients", "ingredient_id", aid,
                          _lookup_id(conn, "ingredients", name))
                for name in _unique(d["products"]):
                    _link(conn, "news_article_products", "product_id", aid,
                          _product_id(conn, name, stats))
                stats["articles"] += 1
        with plat.begin() as conn:
            stats.update(_finalize(conn))
        return stats
    finally:
        plat.dispose()


def main() -> None:
    print(f"[platform] {publish_to_platform()}")


if __name__ == "__main__":
    main()
