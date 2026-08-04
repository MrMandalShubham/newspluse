"""Base collector — the shared, reusable machinery every source builds on.

Responsibilities kept generic (no site-specific logic here):
  * polite HTTP fetching (custom User-Agent, rate limiting, retry/backoff)
  * robots.txt respect
  * provenance capture + content hashing for dedup

All network access goes through a single httpx.Client, so tests can inject a
MockTransport and run fully offline.
"""

import hashlib
import time
from abc import ABC, abstractmethod
from datetime import datetime
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import BaseModel, Field

from newspulse.config import settings

# HTTP statuses worth retrying (rate limit + transient server errors).
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class CollectedItem(BaseModel):
    """A normalized item emitted by any collector, with provenance."""

    source_name: str
    url: str
    title: str | None = None
    body: str | None = None
    published_at: datetime | None = None
    lang: str | None = None
    keywords: list[str] = Field(default_factory=list)


def content_hash(text: str) -> str:
    """Deterministic SHA-256 of the given text (used for dedup)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BaseCollector(ABC):
    """Abstract collector. Subclasses implement :meth:`collect`."""

    min_interval: float = 1.0  # min seconds between requests (politeness)
    max_retries: int = 3
    backoff_base: float = 0.5  # seconds; grows as backoff_base * 2**attempt
    timeout: float = 25.0

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.user_agent = settings.user_agent
        self._client = client or httpx.Client(
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout,
            follow_redirects=True,
        )
        self._last_request = 0.0
        self._robots: dict[str, RobotFileParser] = {}

    # --- politeness -----------------------------------------------------
    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _robots_for(self, url: str) -> RobotFileParser:
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = RobotFileParser()
            try:
                resp = self._client.get(f"{base}/robots.txt")
                rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except httpx.HTTPError:
                rp.parse([])  # unreachable robots.txt -> assume allowed
            self._robots[base] = rp
        return rp

    def can_fetch(self, url: str) -> bool:
        """Whether robots.txt permits fetching ``url`` for our User-Agent."""
        return self._robots_for(url).can_fetch(self.user_agent, url)

    # --- fetching -------------------------------------------------------
    def fetch(self, url: str) -> str:
        """Fetch ``url`` politely, with retry/backoff. Raises on final failure."""
        if not self.can_fetch(url):
            raise PermissionError(f"robots.txt disallows fetching {url}")

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                resp = self._client.get(url)
                if resp.status_code in RETRYABLE_STATUS:
                    raise httpx.HTTPStatusError(
                        f"retryable status {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                return resp.text
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff_base * (2**attempt))
        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self._client.close()

    # --- contract -------------------------------------------------------
    @abstractmethod
    def collect(self) -> list[CollectedItem]:
        """Fetch from the source and return normalized items."""
