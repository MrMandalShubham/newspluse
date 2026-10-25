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
import time
import uuid
from datetime import date, timedelta

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError

from newspulse.config import settings
from newspulse.db import Base, SessionLocal
from newspulse.models import ArticleReport, RawItem, ReportCluster, Source
from newspulse.publish.matcher import CatalogMatcher
from newspulse.publish.models import (
    Company,
    Ingredient,
    Lead,
    NewsArticleBrand,
    NewsArticleCompany,
    NewsArticleIngredient,
    NewsArticleProduct,
    NewsPulseArticle,
    Theme,
    ThemeAlias,
    ThemeRelation,
    TopicCluster,
    TopicClusterMember,
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
    TopicCluster.__table__,
    TopicClusterMember.__table__,
    Lead.__table__,
    Theme.__table__,
    ThemeAlias.__table__,
    ThemeRelation.__table__,
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
    "TH": ("Thailand", "TH", "🇹🇭"),
    "TW": ("Taiwan", "TW", "🇹🇼"),
    "EU": ("Europe", "EU", "🇪🇺"),
    "SG": ("Singapore", "SG", "🇸🇬"),
    "MY": ("Malaysia", "MY", "🇲🇾"),
    "AU": ("Australia", "AU", "🇦🇺"),
    "FR": ("France", "FR", "🇫🇷"),
}

_JUNCTIONS = ("news_article_brands", "news_article_companies",
              "news_article_ingredients", "news_article_products")

# LLM-extracted country name -> our region code (falls back to source region).
COUNTRY_TO_REGION = {
    "south korea": "KR", "korea": "KR", "republic of korea": "KR", "kr": "KR",
    "china": "CN", "mainland china": "CN", "prc": "CN", "cn": "CN",
    "japan": "JP", "jp": "JP",
    "hong kong": "HK", "hong kong sar": "HK", "hk": "HK",
    "india": "IN", "in": "IN",
    "indonesia": "ID", "id": "ID",
    "united states": "US", "usa": "US", "u.s.": "US", "us": "US",
    "united states of america": "US", "america": "US",
    "united kingdom": "GB", "uk": "GB", "u.k.": "GB",
    "britain": "GB", "england": "GB", "gb": "GB",
    "thailand": "TH", "th": "TH",
    "taiwan": "TW", "republic of china": "TW", "tw": "TW",
    "eu": "EU", "europe": "EU",
    "singapore": "SG", "sg": "SG",
    "malaysia": "MY", "my": "MY",
    "australia": "AU", "au": "AU",
    "france": "FR", "fr": "FR",
}


def _country_to_region(country: str | None) -> str | None:
    if not country:
        return None
    return COUNTRY_TO_REGION.get(country.strip().lower())


def normalize_region(raw: str | None) -> str | None:
    """Convert any region string to a canonical ISO-2 code (or None)."""
    if not raw:
        return None
    code = raw.strip().upper()
    if code in MARKET_MAP:
        return code
    return COUNTRY_TO_REGION.get(raw.strip().lower())


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


def _resolve_story_id(conn, headline: str, published_at, fallback_id: str | None) -> str | None:
    """Find an existing story_id with a similar headline within 48h, or use the fallback."""
    if not headline or published_at is None:
        return fallback_id
    row = conn.execute(
        text(
            "SELECT story_id, similarity(headline, :hl) AS sim "
            "FROM news_pulse_articles "
            "WHERE story_id IS NOT NULL "
            "  AND published_at > :since "
            "  AND similarity(headline, :hl) > 0.85 "
            "ORDER BY sim DESC LIMIT 1"
        ),
        {"hl": headline, "since": published_at - _48H},
    ).first()
    if row:
        return row.story_id
    return fallback_id


_48H = timedelta(hours=48)


def _upsert_article(conn, d, market_id):
    story_id = _resolve_story_id(
        conn, d["headline"], d["published_at"], d.get("story_id"),
    )
    fields = {
        "headline": d["headline"], "summary": d["summary"], "source": d["source"],
        "source_tier": d["source_tier"], "market_id": market_id, "category": d["category"],
        "sentiment": d["sentiment"], "theme": d["theme"], "reach": None,
        "image_url": d.get("image_url"),
        "published_at": d["published_at"], "signal_tier": d["signal_tier"],
        "topic_velocity": d["topic_velocity"],
        "importance_score": d["importance_score"],
        "event_types": json.dumps(d["event_types"] or []),
        "story_id": story_id,
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
                 "event_types=cast(:event_types as jsonb), story_id=:story_id where id=:id"),
            {**fields, "id": aid},
        )
    else:
        aid = uuid.uuid4()
        conn.execute(
            text("insert into news_pulse_articles(id,slug,story_id,url,headline,summary,source,"
                 "source_tier,market_id,category,sentiment,theme,reach,image_url,published_at,"
                 "signal_tier,topic_velocity,importance_score,event_types,created_at) values("
                 ":id,:slug,:story_id,:url,:headline,:summary,:source,:source_tier,:market_id,"
                 ":category,:sentiment,:theme,:reach,:image_url,:published_at,:signal_tier,"
                 ":topic_velocity,:importance_score,cast(:event_types as jsonb), now())"),
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


def _collect_rows(since: date | None = None) -> list[dict]:
    """Collect article rows from working DB.

    When ``since`` is given, only articles created on or after that date are
    returned — this makes incremental publishes fast (seconds instead of hours).
    """
    work = SessionLocal()
    try:
        q = (
            select(ArticleReport, RawItem, Source)
            .join(RawItem, RawItem.id == ArticleReport.raw_item_id)
            .join(Source, Source.id == RawItem.source_id)
            .where(ArticleReport.is_product_related.is_(True))
        )
        if since is not None:
            q = q.where(ArticleReport.created_at >= since)
        rows = work.execute(q.order_by(ArticleReport.id)).all()
        out = []
        for ar, ri, src in rows:
            size = 1
            story_id = None
            if ar.cluster_id is not None:
                cluster = work.get(ReportCluster, ar.cluster_id)
                if cluster:
                    size = cluster.size
                    story_id = f"story-{cluster.id}"
            out.append({
                "url": ri.url, "headline": ar.title or ri.title or ri.url,
                "image_url": ri.image_url,
                "summary": ar.summary, "source": src.name,
                "source_tier": _source_tier(src.trust_score),
                "region": (
                    _country_to_region(ar.country)
                    or normalize_region(src.region)
                    or src.region
                ),
                "category": ar.category, "sentiment": ar.sentiment, "theme": ar.theme,
                "event_types": ar.event_types,
                "importance_score": _hybrid_importance(ar.importance_score, size),
                "published_at": ri.published_at or ar.created_at,
                "signal_tier": _signal_tier(size),
                "topic_velocity": float(size), "brands": ar.brands, "companies": ar.companies,
                "ingredients": ar.ingredients, "products": ar.products,
                "story_id": story_id,
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


def _slug_sql(col: str, fallback: str) -> str:
    """SQL expression building a URL-safe, unique slug: {name-slug}-{id6}."""
    base = f"trim(both '-' from regexp_replace(lower({col}),'[^a-z0-9]+','-','g'))"
    return (
        f"coalesce(nullif(left({base},80),''),'{fallback}') "
        "|| '-' || substr(replace(id::text,'-',''),1,6)"
    )


def _ensure_entity_slugs(conn) -> dict:
    """Add + backfill stable slugs on brands/ingredients (and news-only products).

    Brand/ingredient hubs need permanent URL slugs. products_master already has a
    slug (retail rows) so only news-created ones are filled. Additive + idempotent.
    """
    out = {}
    for tbl, fallback in (("brands", "brand"), ("ingredients", "ingredient")):
        conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS slug TEXT"))
        conn.execute(
            text(f"CREATE INDEX IF NOT EXISTS ix_{tbl}_slug ON {tbl}(slug)")
        )
        r = conn.execute(
            text(f"UPDATE {tbl} SET slug = {_slug_sql('name', fallback)} WHERE slug IS NULL")
        )
        out[f"{tbl}_slugs"] = r.rowcount
    r = conn.execute(
        text(f"UPDATE products_master SET slug = {_slug_sql('name', 'product')} "
             "WHERE slug IS NULL AND data_source='newspulse'")
    )
    out["product_slugs"] = r.rowcount
    return out


_MARKET_MERGE = {
    "Japan": "JP", "japan": "JP", "jp": "JP",
    "China": "CN", "china": "CN", "cn": "CN",
    "Korea": "KR", "korea": "KR", "kr": "KR", "Korea (Global)": "KR",
    "Thailand": "TH", "thailand": "TH", "th": "TH",
    "India": "IN", "india": "IN",
    "eu": "EU", "EU": "EU",
    "gb": "GB",
    "XG": None,
}


def _merge_duplicate_markets(conn) -> int:
    """Merge non-ISO market rows into their canonical ISO counterparts."""
    merged = 0
    for old_code, target_iso in _MARKET_MERGE.items():
        old = conn.execute(
            text("SELECT id FROM markets WHERE code=:c"), {"c": old_code}
        ).first()
        if not old:
            continue
        if target_iso is None:
            cnt = conn.execute(
                text("SELECT count(*) FROM news_pulse_articles WHERE market_id=:m"),
                {"m": old[0]},
            ).scalar()
            if cnt == 0:
                conn.execute(text("DELETE FROM markets WHERE id=:id"), {"id": old[0]})
                merged += 1
            continue
        target = conn.execute(
            text("SELECT id FROM markets WHERE code=:c"), {"c": target_iso}
        ).first()
        if not target:
            name, code, flag = MARKET_MAP.get(target_iso, (target_iso, target_iso, None))
            tid = uuid.uuid4()
            conn.execute(
                text("INSERT INTO markets(id,name,code,region,flag,created_at) "
                     "VALUES(:id,:n,:c,:r,:f, now())"),
                {"id": tid, "n": name, "c": code, "r": target_iso, "f": flag},
            )
            target = (tid,)
        if old[0] == target[0]:
            continue
        conn.execute(
            text("UPDATE news_pulse_articles SET market_id=:new WHERE market_id=:old"),
            {"new": target[0], "old": old[0]},
        )
        conn.execute(text("DELETE FROM markets WHERE id=:id"), {"id": old[0]})
        merged += 1
    return merged


def _finalize(conn) -> dict:
    """Idempotent post-publish: merge markets, backfill slugs/dates, brand-count view."""
    markets_merged = _merge_duplicate_markets(conn)
    rows = conn.execute(
        text("select id, headline from news_pulse_articles where slug is null")
    ).all()
    for r in rows:
        conn.execute(
            text("update news_pulse_articles set slug=:s where id=:id"),
            {"s": article_slug(r.headline, r.id), "id": r.id},
        )
    dates_fixed = conn.execute(
        text(
            "update news_pulse_articles "
            "set published_at = created_at "
            "where published_at is null"
        )
    ).rowcount
    entity = _ensure_entity_slugs(conn)
    conn.execute(text(_BRAND_COUNT_VIEW))
    return {
        "article_slugs_backfilled": len(rows),
        "dates_backfilled": dates_fixed,
        "markets_merged": markets_merged,
        **entity,
    }


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


def publish_to_platform(since: date | None = None) -> dict:
    """Publish articles to platform DB.

    ``since``: only publish articles created on/after this date. Defaults to
    None (all articles — used for initial full publish). For weekly updates,
    pass a date ~10 days back to cover the window with margin.
    """
    plat = create_engine(settings.publish_database_url)
    Base.metadata.create_all(plat, tables=NEW_TABLES, checkfirst=True)
    with plat.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
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
        conn.execute(
            text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_tool_id TEXT")
        )
        conn.execute(
            text("ALTER TABLE news_pulse_articles ADD COLUMN IF NOT EXISTS story_id TEXT")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_news_pulse_articles_story_id "
                 "ON news_pulse_articles(story_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_news_pulse_articles_headline_trgm "
                 "ON news_pulse_articles USING gin(headline gin_trgm_ops)")
        )
        for facet in ("geography", "category", "need", "ingredient", "values", "channel"):
            conn.execute(
                text(f"CREATE INDEX IF NOT EXISTS ix_themes_facet_{facet} "
                     f"ON themes USING gin(facet_{facet} jsonb_path_ops)")
            )
    data = _collect_rows(since=since)
    stats: dict[str, int] = {
        "articles": 0, "brands_matched": 0, "brands_new": 0,
        "products_matched": 0, "products_new": 0, "markets_new": 0,
    }
    if not data:
        try:
            with plat.begin() as conn:
                stats.update(_finalize(conn))
            return stats
        finally:
            plat.dispose()

    try:
        with plat.begin() as conn:
            # --- Pre-load entity caches (5 bulk SELECTs) ---
            market_cache: dict[str, object] = {}
            for row in conn.execute(text("SELECT id, code FROM markets")):
                market_cache[row[1]] = row[0]

            brand_cache: dict[str, object] = {}
            for row in conn.execute(text("SELECT id, lower(name) FROM brands")):
                brand_cache[row[1]] = row[0]

            product_cache: dict[str, object] = {}
            for row in conn.execute(
                text("SELECT id, lower(name) FROM products_master"),
            ):
                product_cache[row[1]] = row[0]

            company_cache: dict[str, object] = {}
            for row in conn.execute(text("SELECT id, lower(name) FROM companies")):
                company_cache[row[1]] = row[0]

            ingredient_cache: dict[str, object] = {}
            for row in conn.execute(
                text("SELECT id, lower(name) FROM ingredients"),
            ):
                ingredient_cache[row[1]] = row[0]

            # --- Pre-fetch existing articles by URL (1 query) ---
            all_urls = [d["url"] for d in data]
            existing_articles: dict[str, object] = {}
            for row in conn.execute(
                text(
                    "SELECT url, id FROM news_pulse_articles "
                    "WHERE url = ANY(:urls)"
                ),
                {"urls": all_urls},
            ):
                existing_articles[row[0]] = row[1]

            print(
                f"  [publish] caches loaded: {len(market_cache)} markets, "
                f"{len(brand_cache)} brands, {len(product_cache)} products, "
                f"{len(existing_articles)}/{len(data)} existing articles",
                flush=True,
            )

            # --- Process articles with cached lookups ---
            article_ids: list = []
            brand_links: list[dict] = []
            company_links: list[dict] = []
            ingredient_links: list[dict] = []
            product_links: list[dict] = []

            for d in data:
                region = d["region"]
                market_id = None
                if region:
                    if region in market_cache:
                        market_id = market_cache[region]
                    else:
                        name, code, flag = MARKET_MAP.get(
                            region, (region, region, None),
                        )
                        mid = uuid.uuid4()
                        conn.execute(
                            text(
                                "INSERT INTO markets"
                                "(id,name,code,region,flag,created_at) "
                                "VALUES(:id,:n,:c,:r,:f, now())"
                            ),
                            {
                                "id": mid, "n": name, "c": code,
                                "r": region, "f": flag,
                            },
                        )
                        market_cache[code] = mid
                        stats["markets_new"] += 1
                        market_id = mid

                story_id = d.get("story_id")
                fields = {
                    "headline": d["headline"], "summary": d["summary"],
                    "source": d["source"], "source_tier": d["source_tier"],
                    "market_id": market_id, "category": d["category"],
                    "sentiment": d["sentiment"], "theme": d["theme"],
                    "reach": None, "image_url": d.get("image_url"),
                    "published_at": d["published_at"],
                    "signal_tier": d["signal_tier"],
                    "topic_velocity": d["topic_velocity"],
                    "importance_score": d["importance_score"],
                    "event_types": json.dumps(d["event_types"] or []),
                    "story_id": story_id,
                }

                url = d["url"]
                if url in existing_articles:
                    aid = existing_articles[url]
                    conn.execute(
                        text(
                            "UPDATE news_pulse_articles SET "
                            "headline=:headline, summary=:summary, "
                            "source=:source, source_tier=:source_tier, "
                            "market_id=:market_id, category=:category, "
                            "sentiment=:sentiment, theme=:theme, "
                            "reach=:reach, image_url=:image_url, "
                            "published_at=:published_at, "
                            "signal_tier=:signal_tier, "
                            "topic_velocity=:topic_velocity, "
                            "importance_score=:importance_score, "
                            "event_types=cast(:event_types as jsonb), "
                            "story_id=:story_id WHERE id=:id"
                        ),
                        {**fields, "id": aid},
                    )
                else:
                    aid = uuid.uuid4()
                    conn.execute(
                        text(
                            "INSERT INTO news_pulse_articles"
                            "(id,slug,story_id,url,headline,summary,source,"
                            "source_tier,market_id,category,sentiment,theme,"
                            "reach,image_url,published_at,signal_tier,"
                            "topic_velocity,importance_score,event_types,"
                            "created_at) VALUES("
                            ":id,:slug,:story_id,:url,:headline,:summary,"
                            ":source,:source_tier,:market_id,:category,"
                            ":sentiment,:theme,:reach,:image_url,"
                            ":published_at,:signal_tier,:topic_velocity,"
                            ":importance_score,"
                            "cast(:event_types as jsonb), now())"
                        ),
                        {
                            **fields, "id": aid, "url": url,
                            "slug": article_slug(d["headline"], aid),
                        },
                    )

                article_ids.append(aid)

                for name in _unique(d["brands"]):
                    lname = name.strip().lower()
                    if lname in brand_cache:
                        bid = brand_cache[lname]
                        stats["brands_matched"] += 1
                    else:
                        bid = uuid.uuid4()
                        conn.execute(
                            text(
                                "INSERT INTO brands(id,code,name,created_at) "
                                "VALUES(:id,:c,:n, now())"
                            ),
                            {
                                "id": bid,
                                "c": f"{_slug(name)}-{bid.hex[:6]}",
                                "n": name,
                            },
                        )
                        brand_cache[lname] = bid
                        stats["brands_new"] += 1
                    brand_links.append({"a": aid, "e": bid})

                for name in _unique(d["companies"]):
                    lname = name.strip().lower()
                    if lname in company_cache:
                        cid = company_cache[lname]
                    else:
                        cid = uuid.uuid4()
                        conn.execute(
                            text(
                                "INSERT INTO companies(id,name,created_at) "
                                "VALUES(:id,:n, now())"
                            ),
                            {"id": cid, "n": name},
                        )
                        company_cache[lname] = cid
                    company_links.append({"a": aid, "e": cid})

                for name in _unique(d["ingredients"]):
                    lname = name.strip().lower()
                    if lname in ingredient_cache:
                        iid = ingredient_cache[lname]
                    else:
                        iid = uuid.uuid4()
                        conn.execute(
                            text(
                                "INSERT INTO ingredients(id,name,created_at) "
                                "VALUES(:id,:n, now())"
                            ),
                            {"id": iid, "n": name},
                        )
                        ingredient_cache[lname] = iid
                    ingredient_links.append({"a": aid, "e": iid})

                for name in _unique(d["products"]):
                    lname = name.strip().lower()
                    if lname in product_cache:
                        pid = product_cache[lname]
                        stats["products_matched"] += 1
                    else:
                        pid = uuid.uuid4()
                        conn.execute(
                            text(
                                "INSERT INTO products_master"
                                "(id,name,data_source,created_at,updated_at) "
                                "VALUES(:id,:n,'newspulse', now(), now())"
                            ),
                            {"id": pid, "n": name},
                        )
                        product_cache[lname] = pid
                        stats["products_new"] += 1
                    product_links.append({"a": aid, "e": pid})

                stats["articles"] += 1

            # --- Bulk junction deletes (4 queries total) ---
            for tbl in _JUNCTIONS:
                conn.execute(
                    text(f"DELETE FROM {tbl} WHERE article_id = ANY(:ids)"),
                    {"ids": article_ids},
                )

            # --- Bulk junction inserts (executemany) ---
            if brand_links:
                conn.execute(
                    text(
                        "INSERT INTO news_article_brands(article_id,brand_id) "
                        "VALUES(:a,:e) ON CONFLICT DO NOTHING"
                    ),
                    brand_links,
                )
            if company_links:
                conn.execute(
                    text(
                        "INSERT INTO news_article_companies"
                        "(article_id,company_id) "
                        "VALUES(:a,:e) ON CONFLICT DO NOTHING"
                    ),
                    company_links,
                )
            if ingredient_links:
                conn.execute(
                    text(
                        "INSERT INTO news_article_ingredients"
                        "(article_id,ingredient_id) "
                        "VALUES(:a,:e) ON CONFLICT DO NOTHING"
                    ),
                    ingredient_links,
                )
            if product_links:
                conn.execute(
                    text(
                        "INSERT INTO news_article_products"
                        "(article_id,product_id) "
                        "VALUES(:a,:e) ON CONFLICT DO NOTHING"
                    ),
                    product_links,
                )

        with plat.begin() as conn:
            stats.update(_finalize(conn))
        return stats
    finally:
        plat.dispose()


def refresh_platform_signals(batch: int = 100, since: date | None = None) -> dict:
    """Fast, resilient refresh of cluster-derived fields on existing articles.

    Updates only signal_tier, topic_velocity and importance_score (recomputed from
    the current clustering) on news_pulse_articles, matched by url — NO catalog
    re-matching. Commits in batches with pre-ping + retry, so a transient DO
    connection drop only retries the current batch instead of losing the whole run.
    """
    data = _collect_rows(since=since)
    plat = create_engine(settings.publish_database_url, pool_pre_ping=True)
    updated = 0
    try:
        for i in range(0, len(data), batch):
            chunk = data[i:i + batch]
            for attempt in range(4):
                try:
                    with plat.begin() as conn:
                        for d in chunk:
                            sid = _resolve_story_id(
                                conn, d["headline"], d["published_at"], d.get("story_id"),
                            )
                            conn.execute(
                                text("update news_pulse_articles set signal_tier=:st, "
                                     "topic_velocity=:tv, importance_score=:imp, "
                                     "story_id=:sid where url=:u"),
                                {"st": d["signal_tier"], "tv": d["topic_velocity"],
                                 "imp": d["importance_score"], "sid": sid,
                                 "u": d["url"]},
                            )
                    updated += len(chunk)
                    break
                except OperationalError:
                    if attempt == 3:
                        raise
                    time.sleep(2 ** attempt)
    finally:
        plat.dispose()
    return {"updated": updated}


def _create_brand(conn, name: str) -> object:
    bid = uuid.uuid4()
    conn.execute(
        text("insert into brands(id,code,name,created_at) values(:id,:c,:n, now())"),
        {"id": bid, "c": f"{_slug(name)}-{bid.hex[:6]}", "n": name},
    )
    return bid


def _create_product(conn, name: str) -> object:
    pid = uuid.uuid4()
    conn.execute(
        text("insert into products_master(id,name,data_source,created_at,updated_at) "
             "values(:id,:n,'newspulse', now(), now())"),
        {"id": pid, "n": name},
    )
    return pid


def _create_lookup(conn, table: str, name: str) -> object:
    eid = uuid.uuid4()
    conn.execute(
        text(f"insert into {table}(id,name,created_at) values(:id,:n, now())"),
        {"id": eid, "n": name},
    )
    return eid


def rematch_platform_links() -> dict:
    """Re-resolve existing articles' entity links with the retail-preferring matcher.

    For every published article, re-match its extracted brand/product/company/
    ingredient names, PREFERRING real retail SKUs (Olive Young / @cosme) over the
    news-only rows created earlier, and rewrite its junction rows. Runs one
    transaction per article (pre-ping + retry), so a transient DO drop only
    retries that article. New catalog rows are registered in the matcher only
    after their article commits, keeping memory and DB consistent across retries.
    """
    data = _collect_rows()
    plat = create_engine(settings.publish_database_url, pool_pre_ping=True)
    stats = {
        "articles": 0, "brand_links": 0, "product_links": 0, "product_retail_links": 0,
        "company_links": 0, "ingredient_links": 0, "brands_new": 0, "products_new": 0,
        "companies_new": 0, "ingredients_new": 0, "no_article": 0,
    }
    try:
        with plat.connect() as rc:
            matcher = CatalogMatcher(rc)
        for d in data:
            for attempt in range(4):
                try:
                    created: list[tuple[str, str, object]] = []
                    local = {"brand": 0, "product": 0, "retail": 0, "company": 0, "ingredient": 0}
                    with plat.begin() as conn:
                        row = conn.execute(
                            text("select id from news_pulse_articles where url=:u"),
                            {"u": d["url"]},
                        ).first()
                        if not row:
                            stats["no_article"] += 1
                            break
                        aid = row[0]
                        brand_ids = []
                        for name in _unique(d["brands"]):
                            bid = matcher.match_brand(name)
                            if bid is None:
                                bid = _create_brand(conn, name)
                                created.append(("brand", name, bid))
                            brand_ids.append(bid)
                        product_ids = []
                        for name in _unique(d["products"]):
                            pid = matcher.match_product(name, brand_ids)
                            if pid is None:
                                pid = _create_product(conn, name)
                                created.append(("product", name, pid))
                            elif matcher.is_retail(pid):
                                local["retail"] += 1
                            product_ids.append(pid)
                        company_ids = []
                        for name in _unique(d["companies"]):
                            cid = matcher.match_lookup("companies", name)
                            if cid is None:
                                cid = _create_lookup(conn, "companies", name)
                                created.append(("companies", name, cid))
                            company_ids.append(cid)
                        ingredient_ids = []
                        for name in _unique(d["ingredients"]):
                            iid = matcher.match_lookup("ingredients", name)
                            if iid is None:
                                iid = _create_lookup(conn, "ingredients", name)
                                created.append(("ingredients", name, iid))
                            ingredient_ids.append(iid)
                        for tbl in _JUNCTIONS:
                            conn.execute(text(f"delete from {tbl} where article_id=:a"), {"a": aid})
                        for bid in dict.fromkeys(brand_ids):
                            _link(conn, "news_article_brands", "brand_id", aid, bid)
                            local["brand"] += 1
                        for pid in dict.fromkeys(product_ids):
                            _link(conn, "news_article_products", "product_id", aid, pid)
                            local["product"] += 1
                        for cid in dict.fromkeys(company_ids):
                            _link(conn, "news_article_companies", "company_id", aid, cid)
                            local["company"] += 1
                        for iid in dict.fromkeys(ingredient_ids):
                            _link(conn, "news_article_ingredients", "ingredient_id", aid, iid)
                            local["ingredient"] += 1
                    # committed -> register new rows + merge counts
                    for kind, name, eid in created:
                        if kind == "brand":
                            matcher.add_brand(name, eid)
                            stats["brands_new"] += 1
                        elif kind == "product":
                            matcher.add_product(name, eid)
                            stats["products_new"] += 1
                        else:  # "companies" | "ingredients"
                            matcher.add_lookup(kind, name, eid)
                            stats[f"{kind}_new"] += 1
                    stats["brand_links"] += local["brand"]
                    stats["product_links"] += local["product"]
                    stats["product_retail_links"] += local["retail"]
                    stats["company_links"] += local["company"]
                    stats["ingredient_links"] += local["ingredient"]
                    stats["articles"] += 1
                    break
                except OperationalError:
                    if attempt == 3:
                        raise
                    time.sleep(2 ** attempt)
    finally:
        plat.dispose()
    return stats


def _collect_clusters() -> list[dict]:
    """Gather cluster data from the working DB for topic_clusters publish.

    Single query loads all multi-article cluster members at once, then
    aggregates per cluster in Python (avoids N+1 per-cluster queries).
    """
    from collections import Counter, defaultdict

    work = SessionLocal()
    try:
        cluster_map: dict[int, object] = {}
        for cl in work.execute(
            select(ReportCluster).where(ReportCluster.size >= 2)
        ).scalars():
            cluster_map[cl.id] = cl

        if not cluster_map:
            return []

        rows = work.execute(
            select(ArticleReport, RawItem, Source)
            .join(RawItem, RawItem.id == ArticleReport.raw_item_id)
            .join(Source, Source.id == RawItem.source_id)
            .where(ArticleReport.cluster_id.in_(list(cluster_map)))
        ).all()

        members_by_cluster: dict[int, list] = defaultdict(list)
        for ar, ri, src in rows:
            members_by_cluster[ar.cluster_id].append((ar, ri, src))

        out = []
        for cid, cl in cluster_map.items():
            members = members_by_cluster.get(cid)
            if not members:
                continue

            countries: Counter = Counter()
            categories: Counter = Counter()
            sentiments: list[str] = []
            urls: list[str] = []
            sources_seen: set[str] = set()
            for ar, ri, src in members:
                region = _country_to_region(ar.country) or src.region
                if region:
                    countries[region] += 1
                if ar.category:
                    categories[ar.category] += 1
                if ar.sentiment:
                    sentiments.append(ar.sentiment)
                urls.append(ri.url)
                sources_seen.add(src.name)

            primary_country = countries.most_common(1)[0][0] if countries else None
            is_mixed_country = len(countries) > 1 and (
                countries.most_common(1)[0][1] / sum(countries.values()) < 0.6
            )
            primary_category = categories.most_common(1)[0][0] if categories else None
            is_mixed_category = len(categories) > 1 and (
                categories.most_common(1)[0][1] / sum(categories.values()) < 0.6
            )

            pos = sum(1 for s in sentiments if s == "positive")
            neg = sum(1 for s in sentiments if s == "negative")
            total_s = len(sentiments)
            if total_s:
                sentiment = "positive" if pos / total_s > 0.5 else (
                    "negative" if neg / total_s > 0.5 else "mixed"
                )
            else:
                sentiment = None

            out.append({
                "internal_id": cl.id,
                "name": cl.label,
                "description": cl.summary,
                "article_count": cl.size,
                "source_count": len(sources_seen),
                "primary_country": primary_country if not is_mixed_country else None,
                "primary_category": primary_category if not is_mixed_category else None,
                "is_mixed_country": is_mixed_country,
                "is_mixed_category": is_mixed_category,
                "sentiment": sentiment,
                "velocity": float(cl.size),
                "urls": urls,
            })
        return out
    finally:
        work.close()


def publish_topic_clusters() -> dict:
    """Publish topic_clusters + members to the platform DB.

    Atomic: truncates both tables and re-inserts in one transaction.
    Pre-fetches article URL→ID map and uses executemany for bulk inserts.
    """
    cluster_data = _collect_clusters()
    plat = create_engine(settings.publish_database_url, pool_pre_ping=True)
    stats = {"clusters": 0, "members": 0, "skipped_no_article": 0}
    if not cluster_data:
        plat.dispose()
        return stats
    try:
        with plat.begin() as conn:
            conn.execute(text("DELETE FROM topic_cluster_members"))
            conn.execute(text("DELETE FROM topic_clusters"))

            all_urls: set[str] = set()
            for cd in cluster_data:
                all_urls.update(cd["urls"])

            url_to_aid: dict[str, object] = {}
            for row in conn.execute(
                text(
                    "SELECT url, id FROM news_pulse_articles "
                    "WHERE url = ANY(:urls)"
                ),
                {"urls": list(all_urls)},
            ):
                url_to_aid[row[0]] = row[1]

            cluster_rows: list[dict] = []
            member_rows: list[dict] = []

            for cd in cluster_data:
                cid = uuid.uuid4()
                slug = re.sub(
                    r"[^a-z0-9]+", "-", cd["name"].lower(),
                ).strip("-")[:80]
                slug = (
                    f"{slug}-{cid.hex[:6]}" if slug
                    else f"topic-{cid.hex[:6]}"
                )
                cluster_rows.append({
                    "id": cid, "name": cd["name"], "slug": slug,
                    "desc": cd["description"],
                    "acnt": cd["article_count"],
                    "scnt": cd["source_count"],
                    "pc": cd["primary_country"],
                    "pcat": cd["primary_category"],
                    "imc": cd["is_mixed_country"],
                    "imcat": cd["is_mixed_category"],
                    "sent": cd["sentiment"], "vel": cd["velocity"],
                })
                stats["clusters"] += 1

                for url in cd["urls"]:
                    aid = url_to_aid.get(url)
                    if aid:
                        member_rows.append({"cid": cid, "aid": aid})
                        stats["members"] += 1
                    else:
                        stats["skipped_no_article"] += 1

            if cluster_rows:
                conn.execute(
                    text(
                        "INSERT INTO topic_clusters(id, name, slug, "
                        "description, article_count, source_count, "
                        "primary_country, primary_category, "
                        "is_mixed_country, is_mixed_category, "
                        "sentiment, velocity, created_at, updated_at) "
                        "VALUES(:id, :name, :slug, :desc, :acnt, :scnt, "
                        ":pc, :pcat, :imc, :imcat, :sent, :vel, "
                        "now(), now())"
                    ),
                    cluster_rows,
                )
            if member_rows:
                conn.execute(
                    text(
                        "INSERT INTO topic_cluster_members"
                        "(cluster_id, article_id) "
                        "VALUES(:cid, :aid) ON CONFLICT DO NOTHING"
                    ),
                    member_rows,
                )

        return stats
    finally:
        plat.dispose()


def main() -> None:
    print(f"[platform] {publish_to_platform()}")


if __name__ == "__main__":
    main()
