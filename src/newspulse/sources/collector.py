"""GenericCollector — one collector, configured per source.

Composes a discovery strategy and an extraction strategy from the source's
registry config, on top of BaseCollector (rate-limit / retry / robots /
provenance). This replaces per-site collector classes.
"""

from datetime import date

from newspulse.collectors.base import BaseCollector, CollectedItem
from newspulse.sources.discovery import SitemapDiscovery, build_discovery
from newspulse.sources.extraction import build_extractor
from newspulse.sources.registry import SourceConfig


class GenericCollector(BaseCollector):
    def __init__(self, config: SourceConfig, client=None) -> None:
        super().__init__(client=client)
        self.config = config
        self.discovery = build_discovery(config, self)
        self.extractor = build_extractor(config)

    def discover(self) -> list[str]:
        return self.discovery.discover()

    def discover_backfill(self, since: date) -> list[str]:
        # Backfill is currently a sitemap-index capability only.
        if isinstance(self.discovery, SitemapDiscovery):
            return self.discovery.discover_backfill(since)
        return []

    def collect(self) -> list[CollectedItem]:
        return self.collect_urls(self.discover())

    def collect_urls(self, urls: list[str]) -> list[CollectedItem]:
        items: list[CollectedItem] = []
        for url in urls:
            if not self.can_fetch(url):
                continue
            try:
                html = self.fetch(url)
            except Exception:  # noqa: BLE001 - skip a bad article, keep the run going
                continue
            item = self.extractor.extract(url, html)
            if item:
                items.append(item)
        return items
