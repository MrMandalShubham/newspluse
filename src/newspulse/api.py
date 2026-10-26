"""Read-only delivery API — exposes trends, cards, and the report."""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newspulse.config import settings
from newspulse.db import get_session
from newspulse.feeds.service import ArticleFetcher, ingest_article
from newspulse.models import ArticleReport, Entity, RawItem, ReportCluster, Source, Trend, TrendCard
from newspulse.pipeline.report import render_report
from newspulse.reports.embedder import Embedder, MistralEmbedder
from newspulse.reports.render import render_product_report
from newspulse.reports.summarizer import MistralSummarizer, Summarizer
from newspulse.schemas import (
    ClusterMemberOut,
    IngestIn,
    ProductClusterOut,
    TrendCardOut,
    TrendDetailOut,
    TrendOut,
)
from newspulse.storage import get_storage

router = APIRouter()


def _latest_computed_at(session: Session, window: str):
    return session.execute(
        select(func.max(Trend.computed_at)).where(Trend.window == window)
    ).scalar()


def _to_trend_out(trend: Trend, entity: Entity) -> TrendOut:
    return TrendOut(
        trend_id=trend.id,
        rank=trend.rank,
        entity_id=entity.id,
        entity_name=entity.canonical_name,
        entity_type=entity.type,
        window=trend.window,
        mention_count=trend.mention_count,
        velocity=trend.velocity,
        momentum_score=trend.momentum_score,
        sentiment_avg=trend.sentiment_avg,
        computed_at=trend.computed_at,
    )


@router.get("/trends", response_model=list[TrendOut])
def list_trends(
    window: str = Query("30d"),
    limit: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[TrendOut]:
    latest = _latest_computed_at(session, window)
    if latest is None:
        return []
    rows = session.execute(
        select(Trend, Entity)
        .join(Entity, Entity.id == Trend.entity_id)
        .where(Trend.window == window, Trend.computed_at == latest)
        .order_by(Trend.rank)
        .limit(limit)
    ).all()
    return [_to_trend_out(t, e) for t, e in rows]


@router.get("/trends/{trend_id}", response_model=TrendDetailOut)
def get_trend(trend_id: int, session: Session = Depends(get_session)) -> TrendDetailOut:
    trend = session.get(Trend, trend_id)
    if trend is None:
        raise HTTPException(status_code=404, detail="trend not found")
    entity = session.get(Entity, trend.entity_id)
    cards = session.execute(
        select(TrendCard).where(TrendCard.trend_id == trend.id)
    ).scalars().all()
    return TrendDetailOut(
        **_to_trend_out(trend, entity).model_dump(),
        cards=[TrendCardOut.model_validate(c) for c in cards],
    )


@router.get("/cards", response_model=list[TrendCardOut])
def list_cards(
    window: str = Query("30d"),
    limit: int = Query(10, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[TrendCardOut]:
    latest = _latest_computed_at(session, window)
    if latest is None:
        return []
    cards = session.execute(
        select(TrendCard)
        .join(Trend, Trend.id == TrendCard.trend_id)
        .where(Trend.window == window, Trend.computed_at == latest)
        .order_by(Trend.rank)
        .limit(limit)
    ).scalars().all()
    return [TrendCardOut.model_validate(c) for c in cards]


@router.get("/report/latest", response_class=PlainTextResponse)
def latest_report(
    window: str = Query("30d"), session: Session = Depends(get_session)
) -> str:
    markdown = render_report(session, window)
    if not markdown:
        raise HTTPException(status_code=404, detail="no trends for window")
    return markdown


@router.get("/product-report", response_class=PlainTextResponse)
def product_report(session: Session = Depends(get_session)) -> str:
    return render_product_report(session)


@router.get("/product-clusters", response_model=list[ProductClusterOut])
def product_clusters(session: Session = Depends(get_session)) -> list[ProductClusterOut]:
    clusters = session.execute(
        select(ReportCluster).order_by(ReportCluster.size.desc(), ReportCluster.id)
    ).scalars().all()
    result: list[ProductClusterOut] = []
    for cluster in clusters:
        rows = session.execute(
            select(ArticleReport, RawItem, Source)
            .join(RawItem, RawItem.id == ArticleReport.raw_item_id)
            .join(Source, Source.id == RawItem.source_id)
            .where(ArticleReport.cluster_id == cluster.id)
            .order_by(ArticleReport.id)
        ).all()
        products = sorted({p for (ar, _, _) in rows for p in (ar.products or [])})
        result.append(
            ProductClusterOut(
                id=cluster.id,
                label=cluster.label,
                summary=cluster.summary,
                size=cluster.size,
                products=products,
                members=[
                    ClusterMemberOut(title=ri.title, url=ri.url, source=src.name)
                    for (_ar, ri, src) in rows
                ],
            )
        )
    return result


def get_summarizer() -> Summarizer:
    return MistralSummarizer()


def get_embedder() -> Embedder:
    return MistralEmbedder()


@router.post("/ingest")
def ingest_webhook(
    item: IngestIn,
    x_webhook_secret: str | None = Header(default=None),
    session: Session = Depends(get_session),
    summarizer: Summarizer = Depends(get_summarizer),
    embedder: Embedder = Depends(get_embedder),
) -> dict:
    """Event-driven ingestion: relevance-gate one article, store if product news."""
    if settings.webhook_secret and (
        not x_webhook_secret
        or not hmac.compare_digest(settings.webhook_secret, x_webhook_secret)
    ):
        raise HTTPException(status_code=401, detail="invalid webhook secret")
    return ingest_article(
        item.model_dump(),
        session=session,
        storage=get_storage(),
        summarizer=summarizer,
        embedder=embedder,
        fetcher=ArticleFetcher(),
    )
