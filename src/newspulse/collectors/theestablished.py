"""Collector for The Established (https://www.theestablished.com).

Two discovery modes, one shared article-extraction path:

  * news      -> news-sitemap.xml            (fresh, daily trending news)
  * backfill  -> webcontent-sitemap.xml      (one-time history, date-windowed)

Both filter to the beauty section (``/self/beauty/``). Article title, body,
date, and keywords are pulled from each page's JSON-LD (schema.org Article),
which is far more stable than parsing HTML layout.
"""

import html as html_lib
import json
import re
from collections.abc import Iterator
from datetime import date, datetime
from xml.etree import ElementTree as ET

from newspulse.collectors.base import BaseCollector, CollectedItem

SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_CHILD_DATE_RE = re.compile(r"sitemap_(\d{4})-(\d{2})-(\d{2})\.xml")
_ARTICLE_TYPES = {"Article", "NewsArticle", "BlogPosting"}


class EstablishedCollector(BaseCollector):
    source_name = "The Established"
    base_url = "https://www.theestablished.com"
    news_sitemap = f"{base_url}/news-sitemap.xml"
    index_sitemap = f"{base_url}/webcontent-sitemap.xml"
    beauty_marker = "/self/beauty/"

    # --- discovery ------------------------------------------------------
    def discover_news(self) -> list[str]:
        """Beauty article URLs from the fresh news sitemap."""
        root = ET.fromstring(self.fetch(self.news_sitemap))
        return self._beauty_locs(root)

    def discover_backfill(self, since: date) -> list[str]:
        """Beauty article URLs from daily child sitemaps dated >= ``since``."""
        index = ET.fromstring(self.fetch(self.index_sitemap))
        children = []
        for sm in index.findall(f"{SM}sitemap"):
            loc = sm.findtext(f"{SM}loc") or ""
            d = self._child_date(loc)
            if d and d >= since:
                children.append(loc)

        urls: set[str] = set()
        for child in children:
            root = ET.fromstring(self.fetch(child))
            urls.update(self._beauty_locs(root))
        return sorted(urls)

    def _beauty_locs(self, root: ET.Element) -> list[str]:
        locs = []
        for url_el in root.findall(f"{SM}url"):
            loc = url_el.findtext(f"{SM}loc") or ""
            if self.beauty_marker in loc:
                locs.append(loc)
        return locs

    @staticmethod
    def _child_date(loc: str) -> date | None:
        m = _CHILD_DATE_RE.search(loc)
        return date(int(m[1]), int(m[2]), int(m[3])) if m else None

    # --- article extraction --------------------------------------------
    def parse_article(self, url: str, html: str) -> CollectedItem | None:
        data = self._article_ld(html)
        if data is None:
            return None
        body = html_lib.unescape(data.get("articleBody") or "").strip()
        if not body:
            return None
        title = html_lib.unescape(data.get("headline") or "").strip() or None
        return CollectedItem(
            source_name=self.source_name,
            url=url,
            title=title,
            body=body,
            published_at=self._parse_dt(data.get("datePublished")),
            lang="en",
            keywords=self._as_keywords(data.get("keywords")),
        )

    @classmethod
    def _article_ld(cls, html: str) -> dict | None:
        for block in _LD_RE.findall(html):
            try:
                parsed = json.loads(block)
            except json.JSONDecodeError:
                continue
            for obj in cls._iter_dicts(parsed):
                if "articleBody" in obj or obj.get("@type") in _ARTICLE_TYPES:
                    if "articleBody" in obj:
                        return obj
        return None

    @classmethod
    def _iter_dicts(cls, obj: object) -> Iterator[dict]:
        if isinstance(obj, dict):
            yield obj
            for v in obj.values():
                yield from cls._iter_dicts(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from cls._iter_dicts(v)

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _as_keywords(kw: object) -> list[str]:
        if not kw:
            return []
        if isinstance(kw, list):
            return [str(k).strip() for k in kw if str(k).strip()]
        return [k.strip() for k in str(kw).split(",") if k.strip()]

    # --- BaseCollector contract ----------------------------------------
    def collect(self) -> list[CollectedItem]:
        return self.collect_urls(self.discover_news())

    def collect_urls(self, urls: list[str]) -> list[CollectedItem]:
        items: list[CollectedItem] = []
        for url in urls:
            if not self.can_fetch(url):
                continue
            try:
                html = self.fetch(url)
            except Exception:  # noqa: BLE001 - skip a bad article, keep the run going
                continue
            item = self.parse_article(url, html)
            if item:
                items.append(item)
        return items
