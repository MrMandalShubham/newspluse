"""NewsAPI.org adapter — pull beauty news, map to ingest payloads.

NewsAPI is pull-only, so we query it (one API) and feed each article into the
shared ingestion service. Its ``content`` is truncated, so we carry only the
description here and let ingestion fetch the full body.
"""

import httpx

from newspulse.config import settings

EVERYTHING_URL = "https://newsapi.org/v2/everything"


class NewsApiClient:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self.api_key = api_key or settings.newsapi_key
        self._client = client or httpx.Client(timeout=30.0)

    def fetch(
        self, query: str | None = None, page_size: int = 50, from_date: str | None = None
    ) -> list[dict]:
        params = {
            "q": query or settings.newsapi_query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": page_size,
            "apiKey": self.api_key,
        }
        if from_date:
            params["from"] = from_date
        resp = self._client.get(EVERYTHING_URL, params=params)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        return [self._to_payload(a) for a in articles if a.get("url")]

    @staticmethod
    def _to_payload(article: dict) -> dict:
        source = article.get("source") or {}
        return {
            "url": article.get("url"),
            "title": article.get("title"),
            "description": article.get("description"),
            "content": None,  # NewsAPI content is truncated; ingestion fetches full body
            "source_name": source.get("name") or "NewsAPI",
            "published_at": article.get("publishedAt"),
        }

    def close(self) -> None:
        self._client.close()
