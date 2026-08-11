"""Extraction strategies — turn a fetched article page into a CollectedItem.

  * jsonld      — schema.org Article JSON-LD (title/body/date/keywords). Robust
                  where present (e.g. The Established).
  * readability — trafilatura boilerplate removal for arbitrary HTML, with
                  metadata (title/date/tags). The general-purpose fallback.

Selected per source via ``extraction.method`` in the registry.
"""

import html as html_lib
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import UTC, datetime

import trafilatura

from newspulse.collectors.base import CollectedItem
from newspulse.sources.registry import SourceConfig

_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_ARTICLE_TYPES = {"Article", "NewsArticle", "BlogPosting"}

_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::url)?|twitter:image)["\']'
    r'[^>]*content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_IMAGE_RE_REV = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\']'
    r'[^>]*(?:property|name)=["\'](?:og:image(?::url)?|twitter:image)["\']',
    re.IGNORECASE,
)


def extract_image(html: str) -> str | None:
    """Best-effort main image: og:image / twitter:image meta tag (entities decoded)."""
    for pattern in (_OG_IMAGE_RE, _OG_IMAGE_RE_REV):
        match = pattern.search(html)
        if match:
            return html_lib.unescape(match.group(1).strip())
    return None


def _jsonld_image(data: dict) -> str | None:
    img = data.get("image")
    if isinstance(img, str):
        return img
    if isinstance(img, dict):
        return img.get("url")
    if isinstance(img, list) and img:
        first = img[0]
        return first if isinstance(first, str) else (
            first.get("url") if isinstance(first, dict) else None
        )
    return None


class Extractor(ABC):
    def __init__(self, config: SourceConfig) -> None:
        self.config = config

    @abstractmethod
    def extract(self, url: str, html: str) -> CollectedItem | None:
        """Return a CollectedItem, or None if no usable content was found."""


class JsonLdExtractor(Extractor):
    def extract(self, url: str, html: str) -> CollectedItem | None:
        data = self._article_ld(html)
        if data is None:
            return None
        body = html_lib.unescape(data.get("articleBody") or "").strip()
        if not body:
            return None
        title = html_lib.unescape(data.get("headline") or "").strip() or None
        return CollectedItem(
            source_name=self.config.name,
            url=url,
            title=title,
            body=body,
            published_at=self._parse_dt(data.get("datePublished")),
            lang="en",
            image_url=_jsonld_image(data) or extract_image(html),
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


class ReadabilityExtractor(Extractor):
    def extract(self, url: str, html: str) -> CollectedItem | None:
        try:
            doc = trafilatura.bare_extraction(html, with_metadata=True)
        except Exception:  # noqa: BLE001 - arbitrary HTML; treat failures as "no content"
            return None
        if doc is None:
            return None
        body = (getattr(doc, "text", None) or "").strip()
        if not body:
            return None
        keywords = list(getattr(doc, "tags", None) or []) + list(
            getattr(doc, "categories", None) or []
        )
        return CollectedItem(
            source_name=self.config.name,
            url=url,
            title=getattr(doc, "title", None) or None,
            body=body,
            published_at=self._parse_date(getattr(doc, "date", None)),
            lang=getattr(doc, "language", None) or None,
            image_url=extract_image(html) or getattr(doc, "image", None),
            keywords=keywords,
        )

    @staticmethod
    def _parse_date(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return None


_EXTRACTORS = {"jsonld": JsonLdExtractor, "readability": ReadabilityExtractor}


def build_extractor(config: SourceConfig) -> Extractor:
    return _EXTRACTORS[config.extraction.method](config)
