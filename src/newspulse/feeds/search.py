"""Search-based discovery via SerpAPI (Google Search).

For general-news domains with no beauty section, we run a site-scoped Google
search for beauty terms (per the provided source list: domain + gl/hl/tbs) and
map each result to an ingest payload. The article body is fetched + cleaned by
the shared ingestion service, not taken from the search snippet.
"""

from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel

from newspulse.config import settings

SERPAPI_URL = "https://serpapi.com/search.json"
DEFAULT_REGISTRY = Path("config/search_sources.yaml")
DEFAULT_QUERY = '("beauty" OR "skincare" OR "cosmetics" OR "makeup" OR "K-beauty" OR "fragrance")'


class SearchSource(BaseModel):
    domain: str
    query: str = DEFAULT_QUERY
    gl: str = "kr"
    hl: str = "en"
    tbs: str = "qdr:m,sbd:1"  # last month, sorted by date
    region: str | None = None


def load_search_sources(path: str | Path = DEFAULT_REGISTRY) -> list[SearchSource]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [SearchSource(**entry) for entry in (data.get("sources") or [])]


class SerpApiClient:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self.api_key = api_key or settings.serpapi_key
        self._client = client or httpx.Client(timeout=30.0)

    def search(self, source: SearchSource, num: int = 20) -> list[dict]:
        params = {
            "engine": "google",
            "q": f"site:{source.domain} {source.query}",
            "gl": source.gl,
            "hl": source.hl,
            "tbs": source.tbs,
            "num": num,
            "api_key": self.api_key,
        }
        resp = self._client.get(SERPAPI_URL, params=params)
        resp.raise_for_status()
        results = resp.json().get("organic_results", [])
        return [self._to_payload(r, source) for r in results if r.get("link")]

    @staticmethod
    def _to_payload(result: dict, source: SearchSource) -> dict:
        return {
            "url": result.get("link"),
            "title": result.get("title"),
            "description": result.get("snippet"),
            "content": None,  # fetched + cleaned by ingestion
            "source_name": result.get("source") or source.domain,
            "published_at": None,  # relative in SerpAPI; readability supplies the real date
            "region": source.region,
        }

    def close(self) -> None:
        self._client.close()
