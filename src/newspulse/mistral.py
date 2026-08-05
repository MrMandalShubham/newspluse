"""Shared Mistral chat client (JSON mode) with retry/backoff.

One place for the REST call so enrichment and synthesis don't duplicate it.
All access goes through an injected httpx.Client, so tests use MockTransport.
"""

import time

import httpx

API_URL = "https://api.mistral.ai/v1/chat/completions"
EMBED_URL = "https://api.mistral.ai/v1/embeddings"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def chat_json(
    client: httpx.Client,
    api_key: str,
    model: str,
    system: str,
    user: str,
    *,
    max_retries: int = 3,
    backoff_base: float = 0.5,
    temperature: float = 0.0,
) -> tuple[str, dict | None]:
    """Call Mistral chat in JSON mode. Returns (content, usage). Retries transient errors."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
    }
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = client.post(
                API_URL, headers={"Authorization": f"Bearer {api_key}"}, json=payload
            )
            if resp.status_code in RETRYABLE_STATUS:
                raise httpx.HTTPStatusError(
                    f"retryable status {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"], data.get("usage")
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(backoff_base * (2**attempt))
    assert last_exc is not None
    raise last_exc


def embed_texts(
    client: httpx.Client,
    api_key: str,
    texts: list[str],
    model: str = "mistral-embed",
    *,
    max_retries: int = 3,
    backoff_base: float = 0.5,
) -> list[list[float]]:
    """Return an embedding vector per input text. Retries transient errors."""
    if not texts:
        return []
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = client.post(
                EMBED_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "input": texts},
            )
            if resp.status_code in RETRYABLE_STATUS:
                raise httpx.HTTPStatusError(
                    f"retryable status {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return [row["embedding"] for row in resp.json()["data"]]
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(backoff_base * (2**attempt))
    assert last_exc is not None
    raise last_exc
