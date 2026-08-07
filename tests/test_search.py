"""Search adapter (SerpAPI) mapping, offline via MockTransport."""

import httpx

from newspulse.feeds.search import SearchSource, SerpApiClient, load_search_sources

RESPONSE = {
    "organic_results": [
        {
            "link": "https://www.chosun.com/english/beauty/k-beauty-exports-rise",
            "title": "K-beauty exports rise",
            "snippet": "Amorepacific and others...",
            "source": "The Chosun Ilbo",
        },
        {"title": "no link here"},
    ]
}


def _handler(request: httpx.Request) -> httpx.Response:
    assert "serpapi.com" in str(request.url)
    return httpx.Response(200, json=RESPONSE)


def test_search_maps_and_drops_linkless() -> None:
    transport = httpx.MockTransport(_handler)
    client = SerpApiClient(api_key="k", client=httpx.Client(transport=transport))
    payloads = client.search(SearchSource(domain="chosun.com/english", region="KR"), num=10)
    assert len(payloads) == 1
    p = payloads[0]
    assert p["url"].endswith("/k-beauty-exports-rise")
    assert p["source_name"] == "The Chosun Ilbo"
    assert p["region"] == "KR"
    assert p["content"] is None  # body fetched by ingestion, not from snippet


def test_search_registry_loads() -> None:
    sources = load_search_sources()  # config/search_sources.yaml
    assert any(s.domain == "chosun.com/english" for s in sources)
    assert all(s.region == "KR" for s in sources)
