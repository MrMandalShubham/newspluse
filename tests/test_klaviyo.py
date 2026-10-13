"""Tests for the Klaviyo integration client."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from newspulse.integrations import klaviyo


@pytest.fixture(autouse=True)
def _enable_klaviyo(monkeypatch):
    monkeypatch.setattr("newspulse.integrations.klaviyo.settings.klaviyo_api_key", "pk_test_123")
    monkeypatch.setattr("newspulse.integrations.klaviyo.settings.klaviyo_list_id", "LIST_ABC")


def _mock_response(status_code: int, body: dict | None = None):
    resp = httpx.Response(
        status_code,
        json=body or {},
        request=httpx.Request("POST", "https://a.klaviyo.com/api/test"),
    )
    return resp


@pytest.mark.asyncio
async def test_upsert_profile_created():
    resp = _mock_response(201, {"data": {"id": "PROF_1"}})
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp):
        pid = await klaviyo.upsert_profile("test@example.com", name="Jane Doe")
    assert pid == "PROF_1"


@pytest.mark.asyncio
async def test_upsert_profile_duplicate():
    resp = _mock_response(409, {
        "errors": [{"meta": {"duplicate_profile_id": "PROF_DUP"}}],
    })
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp):
        pid = await klaviyo.upsert_profile("dupe@example.com")
    assert pid == "PROF_DUP"


@pytest.mark.asyncio
async def test_subscribe_to_list_success():
    resp = _mock_response(204)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp):
        ok = await klaviyo.subscribe_to_list("PROF_1")
    assert ok is True


@pytest.mark.asyncio
async def test_track_event_success():
    resp = _mock_response(202)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp):
        ok = await klaviyo.track_event("PROF_1", "Lead Status Changed", {"new_status": "confirmed"})
    assert ok is True


@pytest.mark.asyncio
async def test_suppress_profile_success():
    resp = _mock_response(202)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp):
        ok = await klaviyo.suppress_profile("PROF_1")
    assert ok is True


@pytest.mark.asyncio
async def test_disabled_when_no_key(monkeypatch):
    monkeypatch.setattr("newspulse.integrations.klaviyo.settings.klaviyo_api_key", "")
    pid = await klaviyo.upsert_profile("test@example.com")
    assert pid is None


@pytest.mark.asyncio
async def test_get_profile_by_email():
    resp = _mock_response(200, {"data": [{"id": "PROF_FOUND"}]})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=resp):
        pid = await klaviyo.get_profile_by_email("found@example.com")
    assert pid == "PROF_FOUND"


@pytest.mark.asyncio
async def test_get_profile_by_email_not_found():
    resp = _mock_response(200, {"data": []})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=resp):
        pid = await klaviyo.get_profile_by_email("missing@example.com")
    assert pid is None
