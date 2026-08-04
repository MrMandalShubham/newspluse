"""Discovery strategies — find article URLs for a source.

Each strategy fetches through the collector (so rate-limit/retry/robots apply)
and returns article URLs filtered to the source's section. Selected per source
via ``discovery.method`` in the registry.
"""

import re
from abc import ABC, abstractmethod
from datetime import date
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from lxml import html as lxml_html

from newspulse.collectors.base import BaseCollector
from newspulse.sources.registry import SourceConfig

SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
ATOM = "{http://www.w3.org/2005/Atom}"
_CHILD_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


class Discovery(ABC):
    def __init__(self, config: SourceConfig, collector: BaseCollector) -> None:
        self.config = config
        self.collector = collector

    def _abs(self, path: str) -> str:
        return urljoin(self.config.url, path)

    def _keep(self, url: str) -> bool:
        sf = self.config.section_filter
        return sf is None or sf in url

    @abstractmethod
    def discover(self) -> list[str]:
        """Return fresh article URLs for this source."""


class SitemapDiscovery(Discovery):
    def discover(self) -> list[str]:
        d = self.config.discovery
        if not d.news_sitemap:
            return []
        root = ET.fromstring(self.collector.fetch(self._abs(d.news_sitemap)))
        return [u for u in self._locs(root) if u and self._keep(u)]

    def discover_backfill(self, since: date) -> list[str]:
        """Article URLs from daily child sitemaps dated >= ``since``."""
        d = self.config.discovery
        if not d.index_sitemap:
            return []
        index = ET.fromstring(self.collector.fetch(self._abs(d.index_sitemap)))
        children = []
        for sm in index.findall(f"{SM}sitemap"):
            loc = sm.findtext(f"{SM}loc") or ""
            dt = self._child_date(loc)
            if dt and dt >= since:
                children.append(loc)
        urls: set[str] = set()
        for child in children:
            root = ET.fromstring(self.collector.fetch(child))
            urls.update(u for u in self._locs(root) if u and self._keep(u))
        return sorted(urls)

    @staticmethod
    def _locs(root: ET.Element) -> list[str]:
        # Strip: some sitemaps wrap <loc> in CDATA with surrounding whitespace.
        return [(url.findtext(f"{SM}loc") or "").strip() for url in root.findall(f"{SM}url")]

    @staticmethod
    def _child_date(loc: str) -> date | None:
        m = _CHILD_DATE_RE.search(loc)
        return date(int(m[1]), int(m[2]), int(m[3])) if m else None


class RssDiscovery(Discovery):
    def discover(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for feed in self.config.discovery.feeds:
            root = ET.fromstring(self.collector.fetch(self._abs(feed)))
            for url in self._links(root):
                if url and self._keep(url) and url not in seen:
                    seen.add(url)
                    out.append(url)
        return out

    @staticmethod
    def _links(root: ET.Element) -> list[str]:
        links: list[str] = []
        for item in root.iter("item"):  # RSS 2.0
            link = item.findtext("link")
            if link:
                links.append(link.strip())
        for entry in root.iter(f"{ATOM}entry"):  # Atom
            for link_el in entry.findall(f"{ATOM}link"):
                if link_el.get("rel", "alternate") == "alternate" and link_el.get("href"):
                    links.append(link_el.get("href").strip())
        return links


class HtmlCrawlDiscovery(Discovery):
    def discover(self) -> list[str]:
        d = self.config.discovery
        pattern = re.compile(d.link_pattern) if d.link_pattern else None
        seen: set[str] = set()
        out: list[str] = []
        for page in d.list_pages:
            page_url = self._abs(page)
            doc = lxml_html.fromstring(self.collector.fetch(page_url))
            for href in doc.xpath("//a/@href"):
                url = urljoin(page_url, href)
                if url in seen or not self._keep(url):
                    continue
                if pattern and not pattern.search(url):
                    continue
                seen.add(url)
                out.append(url)
        return out


_STRATEGIES = {
    "sitemap": SitemapDiscovery,
    "rss": RssDiscovery,
    "htmlcrawl": HtmlCrawlDiscovery,
}


def build_discovery(config: SourceConfig, collector: BaseCollector) -> Discovery:
    return _STRATEGIES[config.discovery.method](config, collector)
