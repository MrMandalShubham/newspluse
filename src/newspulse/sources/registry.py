"""Source registry — declarative config for every source.

The registry (config/sources.yaml) is the source of truth for HOW to collect a
site. Its identity fields are synced into the ``sources`` table so raw_items can
reference a real source row; the discovery/extraction config drives collection.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from newspulse.db import SessionLocal
from newspulse.models import Source

DEFAULT_REGISTRY = Path("config/sources.yaml")


class DiscoveryConfig(BaseModel):
    method: Literal["sitemap", "rss", "htmlcrawl"]
    # sitemap
    news_sitemap: str | None = None
    index_sitemap: str | None = None
    # rss
    feeds: list[str] = Field(default_factory=list)
    # htmlcrawl
    list_pages: list[str] = Field(default_factory=list)
    link_pattern: str | None = None


class ExtractionConfig(BaseModel):
    # Extraction always runs on the fetched article HTML. RSS is a discovery
    # method, not an extraction one — an RSS source uses extraction: readability.
    method: Literal["jsonld", "readability"]


class SourceConfig(BaseModel):
    key: str
    name: str
    url: str
    region: str | None = None
    type: str = "news"
    trust_score: float = 0.5
    section_filter: str | None = None
    discovery: DiscoveryConfig
    extraction: ExtractionConfig


def load_registry(path: str | Path = DEFAULT_REGISTRY) -> list[SourceConfig]:
    """Load and validate the source registry from YAML."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [SourceConfig(**entry) for entry in (data.get("sources") or [])]


def sync_sources(session: Session, configs: list[SourceConfig]) -> dict[str, int]:
    """Upsert registry identities into the ``sources`` table (idempotent)."""
    created = updated = 0
    for cfg in configs:
        src = session.execute(select(Source).where(Source.name == cfg.name)).scalar_one_or_none()
        if src is None:
            session.add(
                Source(
                    name=cfg.name,
                    url=cfg.url,
                    type=cfg.type,
                    region=cfg.region,
                    trust_score=cfg.trust_score,
                )
            )
            created += 1
        else:
            src.url = cfg.url
            src.type = cfg.type
            src.region = cfg.region
            src.trust_score = cfg.trust_score
            updated += 1
    session.commit()
    return {"created": created, "updated": updated}


def sync_from_file(
    path: str | Path = DEFAULT_REGISTRY, session: Session | None = None
) -> dict[str, int]:
    own_session = session is None
    session = session or SessionLocal()
    try:
        return sync_sources(session, load_registry(path))
    finally:
        if own_session:
            session.close()


def main() -> None:
    print(f"[registry] {sync_from_file()}")


if __name__ == "__main__":
    main()
