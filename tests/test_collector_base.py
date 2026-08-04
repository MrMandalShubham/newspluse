"""Part 1.1 gate — base collector machinery, fully offline via MockTransport."""

import time

import httpx
import pytest

from newspulse.collectors.base import BaseCollector, CollectedItem, content_hash

ROBOTS_ALLOW = "User-agent: *\nAllow: /"
ROBOTS_DISALLOW = "User-agent: *\nDisallow: /"


class _Collector(BaseCollector):
    """Concrete test collector with no real waiting."""

    min_interval = 0.0
    backoff_base = 0.0

    def collect(self) -> list[CollectedItem]:
        return []


def _make(handler) -> _Collector:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return _Collector(client=client)


# --- hashing ------------------------------------------------------------
def test_content_hash_is_deterministic() -> None:
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")
    assert len(content_hash("anything")) == 64


# --- provenance model ---------------------------------------------------
def test_collected_item_defaults() -> None:
    item = CollectedItem(source_name="The Established", url="https://x/y")
    assert item.keywords == []
    assert item.title is None and item.body is None


# --- robots.txt ---------------------------------------------------------
def test_robots_disallow_blocks_fetch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(200, text=ROBOTS_DISALLOW)
        return httpx.Response(200, text="should not be reached")

    c = _make(handler)
    assert c.can_fetch("https://ex.com/secret") is False
    with pytest.raises(PermissionError):
        c.fetch("https://ex.com/secret")


# --- retry / backoff ----------------------------------------------------
def test_fetch_retries_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    seq = [503, 503, 200]
    calls = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(200, text=ROBOTS_ALLOW)
        status = seq[calls["i"]]
        calls["i"] += 1
        return httpx.Response(status, text="OK" if status == 200 else "err")

    c = _make(handler)
    assert c.fetch("https://ex.com/a") == "OK"
    assert calls["i"] == 3  # two retries then success


def test_fetch_exhausts_retries(monkeypatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    calls = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(200, text=ROBOTS_ALLOW)
        calls["i"] += 1
        return httpx.Response(503, text="err")

    c = _make(handler)
    with pytest.raises(httpx.HTTPStatusError):
        c.fetch("https://ex.com/a")
    assert calls["i"] == c.max_retries
