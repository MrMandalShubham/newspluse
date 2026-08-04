"""Signal extraction via an LLM (Mistral).

A provider-agnostic ``SignalExtractor`` interface with two implementations:
  * ``MistralExtractor`` — calls Mistral's REST chat API (JSON mode) over httpx.
  * ``FakeExtractor``   — returns canned results, for offline tests.

The model returns a strict JSON shape which we validate with Pydantic; anything
malformed degrades to "no mentions" rather than raising, so one bad article
never breaks a run.
"""

import json
import re
from abc import ABC, abstractmethod

import httpx
from pydantic import BaseModel, Field

from newspulse.config import settings
from newspulse.mistral import chat_json

MAX_BODY_CHARS = 8000  # cost guard: cap article text sent to the model

ENTITY_TYPES = {"brand", "product", "ingredient", "category"}
SIGNAL_TYPES = {"launch", "mention", "review", "ranking", "price", "reg"}

SYSTEM_PROMPT = (
    "You are a precise information extractor for beauty-industry market intelligence. "
    "Extract only genuine BEAUTY MARKET entities from the article and classify each.\n"
    "Entity types (choose exactly one):\n"
    "- brand: a cosmetics/beauty/fragrance brand that makes or sells beauty products "
    "(e.g., L'Oreal, Forest Essentials, Chanel).\n"
    "- product: a specific named beauty product (e.g., 'OUAI Detox Shampoo').\n"
    "- ingredient: a cosmetic ingredient or fragrance note (e.g., niacinamide, salicylic acid).\n"
    "- category: a product category or format (e.g., body wash, serum, clarifying shampoo).\n"
    "Do NOT extract (skip entirely): people or individuals (dermatologists, experts, founders, "
    "authors, e.g., 'Dr Madhuri Agarwal'); retailers, marketplaces or websites (e.g., Amazon, "
    "Nykaa, Tira); market-research or data firms (e.g., Mintel, Nielsen); pharmaceutical or "
    "chemical companies that are not beauty brands; generic professions or roles (e.g., "
    "'dermatologist', 'consumer'); publications or media outlets.\n"
    "Prefer precision over recall: if unsure whether something is a genuine beauty "
    "brand/product/ingredient/category, omit it.\n"
    "Return ONLY JSON of the form: "
    '{"mentions":[{"name":str,"type":one of [brand,product,ingredient,category],'
    '"signal_type":one of [launch,mention,review,ranking,price,reg],'
    '"sentiment":number in [-1,1] or null}]}. '
    "Use the provided keywords as hints. Do not invent entities unsupported by the text."
)

# Deterministic safety net: drop clear non-entities the model may still emit.
_PERSON_PREFIX = re.compile(r"^(dr|dr\.|prof|mr|mrs|ms|miss)\b", re.IGNORECASE)
_DOMAIN = re.compile(r"\.(com|in|co|io|net|org)\b", re.IGNORECASE)
_RETAILER_HINTS = {
    "amazon", "nykaa", "tira", "tirabeauty", "flipkart", "myntra",
    "sephora", "ulta", "purplle", "smytten",
}
_RESEARCH_FIRMS = {"mintel", "nielsen", "euromonitor", "statista", "kantar", "gartner"}
_ROLE_WORDS = {
    "dermatologist", "dermatologists", "consumer", "consumers", "expert",
    "experts", "founder", "author", "celebrity", "influencer",
}


def is_noise(name: str) -> bool:
    """True if ``name`` is a person, retailer, research firm, or generic role."""
    n = name.strip().lower()
    if not n:
        return True
    if _PERSON_PREFIX.match(n) or _DOMAIN.search(n):
        return True
    tokens = set(re.split(r"[\s./]+", n))
    if tokens & _RETAILER_HINTS or tokens & _RESEARCH_FIRMS:
        return True
    return n in _ROLE_WORDS


class Mention(BaseModel):
    name: str
    type: str
    signal_type: str
    sentiment: float | None = None


class ExtractionResult(BaseModel):
    mentions: list[Mention] = Field(default_factory=list)


class SignalExtractor(ABC):
    # Populated by implementations that report token usage (None if unknown).
    last_usage: dict | None = None

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

    def extract(self, title: str | None, body: str, keywords: list[str]) -> ExtractionResult:
        user = self._build_user_content(title, body, keywords)
        content, usage = chat_json(self._client, self.api_key, self.model, SYSTEM_PROMPT, user)
        self.last_usage = usage
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
            if (
                m.name
                and m.type in ENTITY_TYPES
                and m.signal_type in SIGNAL_TYPES
                and not is_noise(m.name)
            ):
                mentions.append(m)
        return ExtractionResult(mentions=mentions)
