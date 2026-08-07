"""Article summarizer — classify beauty-product relevance + summarize (Mistral).

One LLM call per article returns: is it about beauty products; a short label; a
product-focused summary; and the named products/brands/ingredients. Malformed
output degrades to "not relevant" rather than raising.
"""

import json
from abc import ABC, abstractmethod

import httpx
from pydantic import BaseModel, Field

from newspulse.config import settings
from newspulse.mistral import chat_json

MAX_BODY_CHARS = 8000

CATEGORIES = {"brand", "market", "regulatory", "ingredient", "retail", "consumer"}
SENTIMENTS = {"positive", "neutral", "negative"}

SYSTEM_PROMPT = (
    "You are a beauty-industry news analyst. Decide whether the article is about "
    "beauty PRODUCTS (specific products, brands, or ingredients/categories in a product "
    "context) and extract structured fields. Return ONLY JSON: "
    '{"is_product_related": true/false, '
    '"category": one of ["brand","market","regulatory","ingredient","retail","consumer"], '
    '"sentiment": one of ["positive","neutral","negative"], '
    '"theme": a short topic tag (e.g. "barrier repair", "clean fragrance"), '
    '"label": a short descriptive title, '
    '"summary": a 2-4 sentence summary of the product news, '
    '"brands": [beauty brand names], '
    '"companies": [parent companies or manufacturers], '
    '"ingredients": [key ingredients], '
    '"products": [specific named products]}. '
    "If it is NOT about beauty products (pure wellbeing, celebrity, general lifestyle), "
    "set is_product_related=false and keep the other fields brief or empty."
)


class ArticleSummary(BaseModel):
    is_product_related: bool = False
    category: str = ""
    sentiment: str = "neutral"
    theme: str = ""
    label: str = ""
    summary: str = ""
    brands: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    ingredients: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)


class Summarizer(ABC):
    last_usage: dict | None = None

    @abstractmethod
    def summarize(self, title: str | None, body: str, keywords: list[str]) -> ArticleSummary:
        """Classify + summarize one article."""


class FakeSummarizer(Summarizer):
    def __init__(self, result: ArticleSummary) -> None:
        self.result = result

    def summarize(self, title: str | None, body: str, keywords: list[str]) -> ArticleSummary:
        return self.result


class MistralSummarizer(Summarizer):
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

    def summarize(self, title: str | None, body: str, keywords: list[str]) -> ArticleSummary:
        user = (
            f"TITLE: {title or ''}\n"
            f"KEYWORDS: {', '.join(keywords)}\n"
            f"ARTICLE:\n{body[:MAX_BODY_CHARS]}"
        )
        content, usage = chat_json(self._client, self.api_key, self.model, SYSTEM_PROMPT, user)
        self.last_usage = usage
        return self.parse(content)

    @staticmethod
    def _as_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if str(v).strip()]

    @staticmethod
    def parse(content: str) -> ArticleSummary:
        try:
            obj = json.loads(content)
        except json.JSONDecodeError:
            return ArticleSummary()
        if not isinstance(obj, dict):
            return ArticleSummary()
        category = str(obj.get("category") or "").strip().lower()
        sentiment = str(obj.get("sentiment") or "").strip().lower()
        return ArticleSummary(
            is_product_related=bool(obj.get("is_product_related", False)),
            category=category if category in CATEGORIES else "",
            sentiment=sentiment if sentiment in SENTIMENTS else "neutral",
            theme=str(obj.get("theme") or "").strip(),
            label=str(obj.get("label") or "").strip(),
            summary=str(obj.get("summary") or "").strip(),
            brands=MistralSummarizer._as_list(obj.get("brands")),
            companies=MistralSummarizer._as_list(obj.get("companies")),
            ingredients=MistralSummarizer._as_list(obj.get("ingredients")),
            products=MistralSummarizer._as_list(obj.get("products")),
        )
