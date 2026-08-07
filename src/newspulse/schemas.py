"""API response models (what the delivery layer returns)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TrendOut(BaseModel):
    trend_id: int
    rank: int | None
    entity_id: int
    entity_name: str
    entity_type: str
    window: str
    mention_count: int
    velocity: float
    momentum_score: float
    sentiment_avg: float | None
    computed_at: datetime


class TrendCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trend_id: int
    title: str
    body: str
    so_what: str | None
    citations: list[dict]
    model: str | None
    created_at: datetime


class TrendDetailOut(TrendOut):
    cards: list[TrendCardOut]


class ClusterMemberOut(BaseModel):
    title: str | None
    url: str
    source: str


class ProductClusterOut(BaseModel):
    id: int
    label: str
    summary: str
    size: int
    products: list[str]
    members: list[ClusterMemberOut]


class IngestIn(BaseModel):
    """Payload accepted by the /ingest webhook (aggregator-agnostic)."""

    url: str
    title: str | None = None
    content: str | None = None
    description: str | None = None
    source_name: str | None = None
    published_at: str | None = None
