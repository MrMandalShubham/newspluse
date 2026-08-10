"""Keyless search discovery via Google News RSS.

Google News RSS search returns recent articles matching a query (no API key).
Its item links are JS-redirect URLs, so we resolve each to the real publisher
article with a headless browser, then hand the HTML to readability + ingestion.
This surfaces scattered Korean/K-beauty news that mentions catalog brands.
"""

from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx

GN_RSS = "https://news.google.com/rss/search"


def _clean_title(title: str, source: str | None) -> str:
    # Google News titles are "Headline - Source"; drop the trailing source.
    if source and title.endswith(f" - {source}"):
        return title[: -(len(source) + 3)].strip()
    return title.strip()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


class GoogleNewsClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            timeout=30.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
        )

    def search(
        self,
        query: str,
        *,
        hl: str = "en-US",
        gl: str = "US",
        ceid: str = "US:en",
        limit: int | None = None,
    ) -> list[dict]:
        resp = self._client.get(GN_RSS, params={"q": query, "hl": hl, "gl": gl, "ceid": ceid})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        items: list[dict] = []
        for item in root.findall(".//item"):
            link = item.findtext("link")
            if not link:
                continue
            source = (item.findtext("source") or "").strip() or None
            items.append(
                {
                    "gnews_url": link,
                    "title": _clean_title(item.findtext("title") or "", source),
                    "source_name": source or "Google News",
                    "published_at": _parse_date(item.findtext("pubDate")),
                }
            )
        return items[:limit] if limit else items

    def close(self) -> None:
        self._client.close()


class GoogleNewsResolver:
    """Resolves a Google News redirect link to (real_url, html) via headless browser."""

    def __init__(self, user_agent: str = "Mozilla/5.0", timeout_ms: int = 30000,
                 settle_ms: int = 2500) -> None:
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms
        self.settle_ms = settle_ms
        self._pw = None
        self._browser = None

    def _ensure(self) -> None:
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)

    def resolve(self, gnews_url: str) -> tuple[str | None, str | None]:
        self._ensure()
        page = self._browser.new_page(user_agent=self.user_agent)
        try:
            page.goto(gnews_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                page.wait_for_url(lambda u: "news.google.com" not in u, timeout=15000)
            except Exception:  # noqa: BLE001 - redirect may already be done; check url below
                pass
            page.wait_for_timeout(self.settle_ms)
            final, html = page.url, page.content()
            if "news.google.com" in final:
                return None, None  # never left Google News
            return final, html
        except Exception:  # noqa: BLE001 - unresolved/blocked article
            return None, None
        finally:
            page.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None
