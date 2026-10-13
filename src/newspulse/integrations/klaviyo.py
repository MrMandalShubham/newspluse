"""Klaviyo REST API v2024-10-15 client for lead sync.

Handles: profile creation, list subscription, and event tracking.
Runs async via httpx so it doesn't block the FastAPI event loop.
"""

from __future__ import annotations

import logging

import httpx

from newspulse.config import settings

log = logging.getLogger(__name__)

BASE = "https://a.klaviyo.com/api"
REVISION = "2024-10-15"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Klaviyo-API-Key {settings.klaviyo_api_key}",
        "revision": REVISION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _enabled() -> bool:
    return bool(settings.klaviyo_api_key and settings.klaviyo_list_id)


async def upsert_profile(
    email: str,
    *,
    name: str | None = None,
    company: str | None = None,
    job_title: str | None = None,
    country: str | None = None,
    source: str | None = None,
    utm_source: str | None = None,
    utm_medium: str | None = None,
    utm_campaign: str | None = None,
) -> str | None:
    """Create or update a Klaviyo profile. Returns the profile ID or None."""
    if not _enabled():
        return None

    properties: dict = {}
    if source:
        properties["lead_source"] = source
    if utm_source:
        properties["utm_source"] = utm_source
    if utm_medium:
        properties["utm_medium"] = utm_medium
    if utm_campaign:
        properties["utm_campaign"] = utm_campaign

    attributes: dict = {"email": email, "properties": properties}
    if name:
        parts = name.split(None, 1)
        attributes["first_name"] = parts[0]
        if len(parts) > 1:
            attributes["last_name"] = parts[1]
    if company:
        attributes["organization"] = company
    if job_title:
        attributes["title"] = job_title
    if country:
        attributes["location"] = {"country": country}

    payload = {"data": {"type": "profile", "attributes": attributes}}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{BASE}/profiles/", json=payload, headers=_headers(),
        )

    if resp.status_code == 201:
        profile_id = resp.json()["data"]["id"]
        log.info("klaviyo: created profile %s for %s", profile_id, email)
        return profile_id

    if resp.status_code == 409:
        dupe = resp.json().get("errors", [{}])[0]
        profile_id = dupe.get("meta", {}).get("duplicate_profile_id")
        if profile_id:
            log.info("klaviyo: profile already exists %s for %s", profile_id, email)
            return profile_id

    log.warning("klaviyo: profile upsert failed %s — %s", resp.status_code, resp.text)
    return None


async def subscribe_to_list(profile_id: str) -> bool:
    """Add a profile to the configured Klaviyo list."""
    if not _enabled() or not profile_id:
        return False

    payload = {
        "data": [{
            "type": "profile",
            "id": profile_id,
        }],
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{BASE}/lists/{settings.klaviyo_list_id}/relationships/profiles/",
            json=payload,
            headers=_headers(),
        )

    if resp.status_code in (200, 204):
        log.info("klaviyo: added %s to list %s", profile_id, settings.klaviyo_list_id)
        return True

    log.warning("klaviyo: list-add failed %s — %s", resp.status_code, resp.text)
    return False


async def track_event(
    profile_id: str,
    event_name: str,
    properties: dict | None = None,
) -> bool:
    """Track a custom event (e.g. 'Lead Status Changed')."""
    if not _enabled() or not profile_id:
        return False

    payload = {
        "data": {
            "type": "event",
            "attributes": {
                "metric": {"data": {"type": "metric", "attributes": {"name": event_name}}},
                "profile": {"data": {"type": "profile", "id": profile_id}},
                "properties": properties or {},
            },
        },
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{BASE}/events/", json=payload, headers=_headers(),
        )

    if resp.status_code in (200, 202):
        log.info("klaviyo: tracked '%s' for %s", event_name, profile_id)
        return True

    log.warning("klaviyo: event failed %s — %s", resp.status_code, resp.text)
    return False


async def suppress_profile(profile_id: str) -> bool:
    """Suppress (unsubscribe) a profile from all email communications."""
    if not _enabled() or not profile_id:
        return False

    payload = {
        "data": {
            "type": "suppression",
            "attributes": {
                "profiles": {
                    "data": [{"type": "profile", "id": profile_id}],
                },
            },
        },
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{BASE}/profiles/suppression/", json=payload, headers=_headers(),
        )

    if resp.status_code in (200, 202, 204):
        log.info("klaviyo: suppressed profile %s", profile_id)
        return True

    log.warning("klaviyo: suppress failed %s — %s", resp.status_code, resp.text)
    return False


async def get_profile_by_email(email: str) -> str | None:
    """Look up a Klaviyo profile ID by email. Returns ID or None."""
    if not _enabled():
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{BASE}/profiles/",
            params={"filter": f'equals(email,"{email}")'},
            headers=_headers(),
        )

    if resp.status_code == 200:
        data = resp.json().get("data", [])
        if data:
            return data[0]["id"]
    return None
