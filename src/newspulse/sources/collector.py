"""GenericCollector — one collector, configured per source.

Composes a discovery strategy and an extraction strategy from the source's
registry config, on top of BaseCollector (rate-limit / retry / robots /
provenance). For JS sites, ``render: playwright`` swaps the fetch layer to a
headless browser; discovery/extraction are unchanged.
"""

from datetime import date

from newspulse.collectors.base import BaseCollector, CollectedItem
from newspulse.sources.discovery import SitemapDiscovery, build_discovery
from newspulse.sources.extraction import build_extractor
from newspulse.sources.registry import SourceConfig
from newspulse.sources.render import PlaywrightRenderer


class GenericCollector(BaseCollector):
    def __init__(self, config: SourceConfig, client=None, renderer=None) -> None:
        super().__init__(client=client)
        self.config = config
        self.discovery = build_discovery(config, self)
        self.extractor = build_extractor(config)
        if config.render == "playwright":
            self._renderer = renderer or PlaywrightRenderer(self.user_agent)
        else:
            self._renderer = None

    def fetch(self, url: str) -> str:
        # Rendered sources go through the browser (still polite: robots + throttle).
        if self._renderer is None:
            return super().fetch(url)
        if not self.can_fetch(url):
            raise PermissionError(f"robots.txt disallows fetching {url}")
        self._throttle()
        return self._renderer.render(url)

    def close(self) -> None:
        if self._renderer is not None:
            self._renderer.close()
        super().close()

    def discover(self) -> list[str]:
        return self.discovery.discover()

    def discover_backfill(self, since: date) -> list[str]:
        if isinstance(self.discovery, SitemapDiscovery):
            return self.discovery.discover_backfill(since)
        return []

    def collect(self) -> list[CollectedItem]:
        return self.collect_urls(self.discover())

    def collect_urls(self, urls: list[str]) -> list[CollectedItem]:
        if self.config.max_articles is not None:
            urls = urls[: self.config.max_articles]
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
