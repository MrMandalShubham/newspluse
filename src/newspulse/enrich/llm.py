"""Signal extraction via an LLM (Mistral).

A provider-agnostic ``SignalExtractor`` interface with two implementations:
  * ``MistralExtractor`` — calls Mistral's REST chat API (JSON mode) over httpx.
  * ``FakeExtractor``   — returns canned results, for offline tests.

The model returns a strict JSON shape which we validate with Pydantic; anything
malformed degrades to "no mentions" rather than raising, so one bad article
never breaks a run.
"""

import json
from abc import ABC, abstractmethod

import httpx
from pydantic import BaseModel, Field

from newspulse.config import settings

MAX_BODY_CHARS = 8000  # cost guard: cap article text sent to the model

ENTITY_TYPES = {"brand", "product", "ingredient", "category"}
SIGNAL_TYPES = {"launch", "mention", "review", "ranking", "price", "reg"}

SYSTEM_PROMPT = (
    "You are a precise information extractor for beauty-industry news. "
    "From the article, extract mentions of beauty ENTITIES and classify each. "
    "Return ONLY JSON of the form: "
    '{"mentions":[{"name":str,"type":one of [brand,product,ingredient,category],'
    '"signal_type":one of [launch,mention,review,ranking,price,reg],'
    '"sentiment":number in [-1,1] or null}]}. '
    "Use the provided keywords as hints. Do not invent entities unsupported by the text."
)


class Mention(BaseModel):
    name: str
    type: str
    signal_type: str
    sentiment: float | None = None


class ExtractionResult(BaseModel):
    mentions: list[Mention] = Field(default_factory=list)


class SignalExtractor(ABC):
    @abstractmethod
    def extract(self, title: str | None, body: str, keywords: list[str]) -> ExtractionResult:
        """Return structured mentions extracted from an article."""


class FakeExtractor(SignalExtractor):
    """Returns a fixed result. Used in tests."""

    def __init__(self, result: ExtractionResult) -> None:
        self.result = result

    def extract(self, title: str | None, body: str, keywords: list[str]) -> ExtractionResult:
        return self.result


class MistralExtractor(SignalExtractor):
    api_url = "https://api.mistral.ai/v1/chat/completions"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or settings.mistral_api_key
        self.model = model or settings.mistral_model
        self._client = client or httpx.Client(timeout=60.0)

    def extract(self, title: str | None, body: str, keywords: list[str]) -> ExtractionResult:
        user = self._build_user_content(title, body, keywords)
        resp = self._client.post(
            self.api_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return self.parse(content)

    @staticmethod
    def _build_user_content(title: str | None, body: str, keywords: list[str]) -> str:
        return (
            f"TITLE: {title or ''}\n"
            f"KEYWORDS: {', '.join(keywords)}\n"
            f"ARTICLE:\n{body[:MAX_BODY_CHARS]}"
        )

    @staticmethod
    def parse(content: str) -> ExtractionResult:
        """Validate the model's JSON; keep only well-formed, in-vocabulary mentions."""
        try:
            obj = json.loads(content)
        except json.JSONDecodeError:
            return ExtractionResult()
        raw = obj.get("mentions", []) if isinstance(obj, dict) else []
        mentions: list[Mention] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                m = Mention(
                    name=str(entry["name"]).strip(),
                    type=str(entry.get("type", "")).lower(),
                    signal_type=str(entry.get("signal_type", "")).lower(),
                    sentiment=entry.get("sentiment"),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if m.name and m.type in ENTITY_TYPES and m.signal_type in SIGNAL_TYPES:
                mentions.append(m)
        return ExtractionResult(mentions=mentions)
