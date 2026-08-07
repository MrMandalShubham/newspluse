"""Part 9.3 — NewsAPI adapter mapping (offline via MockTransport)."""

import httpx

from newspulse.feeds.newsapi import NewsApiClient

RESPONSE = {
    "status": "ok",
    "articles": [
        {
            "source": {"id": None, "name": "Allure"},
            "title": "The best niacinamide serums",
            "description": "A roundup of serums.",
            "url": "https://allure.example/niacinamide-serums",
            "publishedAt": "2026-08-01T10:00:00Z",
            "content": "truncated content [+1200 chars]",
        },
        {
            "source": {"name": "Byrdie"},
            "title": "No url here",
            "description": "skip me",
            "url": None,
        },
    ],
}


def _handler(request: httpx.Request) -> httpx.Response:
    assert "newsapi.org" in str(request.url)
    return httpx.Response(200, json=RESPONSE)


def test_fetch_maps_and_drops_urlless() -> None:
    transport = httpx.MockTransport(_handler)
    client = NewsApiClient(api_key="k", client=httpx.Client(transport=transport))
    payloads = client.fetch(query="beauty", page_size=10)
    assert len(payloads) == 1  # the url-less article is dropped
    p = payloads[0]
    assert p["url"] == "https://allure.example/niacinamide-serums"
    assert p["source_name"] == "Allure"
    assert p["published_at"] == "2026-08-01T10:00:00Z"
    assert p["content"] is None  # truncated NewsAPI content not used; body fetched later
