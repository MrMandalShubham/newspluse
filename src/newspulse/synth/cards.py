"""Trend Card writing via an LLM (Mistral).

The writer produces prose only (title / why / so-what). Citations are attached
separately, by construction, from the real articles backing the trend — the
model never supplies URLs — which is what guarantees citation integrity.
"""

import json
from abc import ABC, abstractmethod

import httpx
from pydantic import BaseModel

from newspulse.config import settings
from newspulse.mistral import chat_json

SYSTEM_PROMPT = (
    "You are a beauty-market analyst writing a concise trend insight for brands "
    "and retailers. Given a trending entity and supporting article headlines, return "
    'ONLY JSON: {"title":str,"body":str,"so_what":str}. '
    "body = 2-4 sentences on why it is trending. "
    "so_what = 1-2 sentences on what a brand or retailer should do. "
    "Base claims only on the provided evidence; do not invent facts or brands."
)


class CardContext(BaseModel):
    entity_name: str
    entity_type: str
    window: str
    volume: int
    velocity: int
    sentiment: float | None
    headlines: list[str]


class CardDraft(BaseModel):
    title: str
    body: str
    so_what: str | None = None


class CardWriter(ABC):
    last_usage: dict | None = None

    @abstractmethod
    def write(self, ctx: CardContext) -> CardDraft:
        """Return a drafted Trend Card for the given context."""


class FakeCardWriter(CardWriter):
    """Returns a fixed draft. Used in tests."""

    def __init__(self, draft: CardDraft) -> None:
        self.draft = draft

    def write(self, ctx: CardContext) -> CardDraft:
        return self.draft


class MistralCardWriter(CardWriter):
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or settings.mistral_api_key
        self.model = model or settings.mistral_model
        self._client = client or httpx.Client(timeout=60.0)
        self.last_usage: dict | None = None

    def write(self, ctx: CardContext) -> CardDraft:
        user = self._build_user_content(ctx)
        content, usage = chat_json(self._client, self.api_key, self.model, SYSTEM_PROMPT, user)
        self.last_usage = usage
        return self.parse(content, ctx)

    @staticmethod
    def _build_user_content(ctx: CardContext) -> str:
        headlines = "\n".join(f"- {h}" for h in ctx.headlines if h)
        sentiment = "n/a" if ctx.sentiment is None else f"{ctx.sentiment:+.2f}"
        return (
            f"ENTITY: {ctx.entity_name} ({ctx.entity_type})\n"
            f"WINDOW: {ctx.window}\n"
            f"MENTIONS: {ctx.volume} (change vs prior window: {ctx.velocity:+d})\n"
            f"AVG SENTIMENT: {sentiment}\n"
            f"SUPPORTING HEADLINES:\n{headlines}"
        )

    @staticmethod
    def parse(content: str, ctx: CardContext) -> CardDraft:
        """Validate JSON; fall back to a stats-based draft if the model misbehaves."""
        try:
            obj = json.loads(content)
            return CardDraft(
                title=str(obj["title"]).strip(),
                body=str(obj["body"]).strip(),
                so_what=(str(obj["so_what"]).strip() if obj.get("so_what") else None),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return CardDraft(
                title=f"{ctx.entity_name} is trending ({ctx.window})",
                body=(
                    f"{ctx.entity_name} appeared in {ctx.volume} beauty articles "
                    f"this {ctx.window} window (change {ctx.velocity:+d} vs prior)."
                ),
                so_what=None,
            )
