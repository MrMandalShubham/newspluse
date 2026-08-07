"""Part 10.3 — publisher maps our data into the demo schema."""

from datetime import datetime

from newspulse.models import ArticleReport, RawItem, ReportCluster, Source
from newspulse.publish.models import (
    Brand,
    Ingredient,
    Market,
    NewsArticleBrand,
    NewsArticleIngredient,
    NewsArticleProduct,
    NewsPulseArticle,
    ProductMaster,
)
from newspulse.publish.publisher import publish


def _seed(session) -> None:
    src = Source(name="The Established", url="https://e", type="news", region="IN", trust_score=0.6)
    session.add(src)
    session.flush()
    cluster = ReportCluster(label="Serum stories", summary="merged", size=3)
    session.add(cluster)
    session.flush()
    ri = RawItem(
        source_id=src.id, url="https://e/serum", title="Serum guide",
        content_hash="h1", published_at=datetime(2026, 8, 1),
    )
    session.add(ri)
    session.flush()
    session.add(
        ArticleReport(
            raw_item_id=ri.id, is_product_related=True, title="Best niacinamide serums",
            summary="A serum roundup.", category="retail", sentiment="positive",
            theme="barrier repair", brands=["CeraVe", "CeraVe"], companies=["L'Oreal"],
            ingredients=["niacinamide", "hyaluronic acid"], products=["CeraVe PM"],
            cluster_id=cluster.id,
        )
    )
    session.commit()


def test_publish_maps_article_and_junctions(db_session) -> None:
    _seed(db_session)
    assert publish(session=db_session) == {"published": 1}

    art = db_session.query(NewsPulseArticle).one()
    assert art.headline == "Best niacinamide serums"
    assert art.source == "The Established"
    assert art.source_tier == "tier-2"  # trust 0.6
    assert art.category == "retail" and art.sentiment == "positive"
    assert art.signal_tier == "emerging-topic"  # cluster size 3
    assert art.topic_velocity == 3.0
    assert art.reach is None

    market = db_session.query(Market).one()
    assert market.name == "India" and market.iso_code == "IN"
    assert art.market_id == market.id

    # junctions + lookups
    assert db_session.query(Brand).count() == 1  # deduped "CeraVe"
    assert db_session.query(NewsArticleBrand).count() == 1
    assert db_session.query(Ingredient).count() == 2
    assert db_session.query(NewsArticleIngredient).count() == 2
    assert db_session.query(ProductMaster).count() == 1
    assert db_session.query(NewsArticleProduct).count() == 1


def test_publish_is_idempotent(db_session) -> None:
    _seed(db_session)
    publish(session=db_session)
    publish(session=db_session)  # re-publish
    assert db_session.query(NewsPulseArticle).count() == 1  # upsert by url
    assert db_session.query(NewsArticleIngredient).count() == 2  # not duplicated
