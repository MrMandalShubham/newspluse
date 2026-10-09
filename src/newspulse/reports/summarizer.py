"""Article summarizer — classify beauty-industry relevance + summarize (Mistral).

One LLM call per article returns: is it relevant to the beauty/cosmetics/personal-care
industry; a short label; a structured summary; and named entities. Malformed output
degrades to "not relevant" rather than raising.
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
# Event-type taxonomy the client asked for (news "what happened"), multi-value.
EVENT_TYPES = {
    "Acquisition", "M&A", "Launch", "Regulatory", "Retail",
    "Ingredient", "Competitor", "Partnership", "Expansion", "Funding",
}
_EVENT_LOOKUP = {e.lower(): e for e in EVENT_TYPES}

SYSTEM_PROMPT = (
    "You are a classifier and analyst for an Asia-focused beauty industry intelligence "
    "platform.\n\n"
    "FIRST QUESTION: Is this article relevant to the beauty, cosmetics, skincare, "
    "personal care, haircare, fragrance/perfume, or related industry?\n"
    "This includes: product launches, brand news, M&A/acquisitions, ingredient trends, "
    "regulatory changes (cosmetics/MFDS/NMPA), retail expansion, beauty retail (Olive Young, "
    "Sephora), K-beauty/J-beauty/C-beauty trends, OEM/ODM manufacturers (Cosmax, Kolmar), "
    "packaging for beauty, beauty-tech, and beauty e-commerce.\n"
    "This does NOT include: general business/trade news, fashion (unless beauty-related), "
    "food/beverage, automotive, real estate, pure celebrity gossip, tech/smartphones, "
    "pharma/medical (unless cosmeceutical), or general lifestyle.\n\n"
    "CLASSIFICATION EXAMPLES:\n"
    'Title: "L\'Oreal Reports Q3 Earnings Beat" -> is_product_related: true\n'
    'Title: "Shiseido Launches New Anti-Aging Serum in Japan" -> is_product_related: true\n'
    'Title: "MFDS Updates Sunscreen Filter Regulations" -> is_product_related: true\n'
    'Title: "Amorepacific Acquires Stake in K-Beauty Startup" -> is_product_related: true\n'
    'Title: "PDRN Emerges as Viral Anti-Aging Ingredient" -> is_product_related: true\n'
    'Title: "Cosmax Opens New Manufacturing Facility in Thailand" -> is_product_related: true\n'
    'Title: "Beauty Retailer Olive Young Expands to U.S." -> is_product_related: true\n'
    'Title: "Celebrity Launches New Skincare Line" -> is_product_related: true\n'
    'Title: "Shipping Container Prices Rise 12% in Q3" -> is_product_related: false\n'
    'Title: "Real Estate Prices in Seoul Decline" -> is_product_related: false\n'
    'Title: "General Trade News: Japan Exports Up 3%" -> is_product_related: false\n'
    'Title: "Fashion Week Highlights: Street Style Trends" -> is_product_related: false\n'
    'Title: "Celebrity Divorce Announcement" -> is_product_related: false\n'
    'Title: "Automotive Industry Reports Strong Sales" -> is_product_related: false\n'
    'Title: "Tech Company Launches New Smartphone" -> is_product_related: false\n'
    'Title: "Hospital Reports New Cancer Treatment" -> is_product_related: false\n\n'
    "After classifying, extract structured fields. Return ONLY JSON:\n"
    '{"is_product_related": true/false, '
    '"category": one of ["brand","market","regulatory","ingredient","retail","consumer"], '
    '"sentiment": one of ["positive","neutral","negative"], '
    '"theme": a short topic tag (e.g. "barrier repair", "clean fragrance"), '
    '"event_types": a list of one or more of '
    '["Acquisition","M&A","Launch","Regulatory","Retail","Ingredient","Competitor",'
    '"Partnership","Expansion","Funding"] describing what happened, '
    '"importance_score": an integer 1-10 for how impactful this news is to the '
    "beauty industry (10 = major M&A / regulation / market shift; 1 = minor blog note), "
    '"country": the country the news is chiefly about (full English name, e.g. '
    '"South Korea", "Japan", "China", or "" if unclear), '
    '"label": a short descriptive title, '
    '"summary": an informative 3-5 sentence summary that covers WHAT happened, '
    "WHY it matters, and the likely IMPACT on the market or category, "
    '"brands": [beauty brand names mentioned], '
    '"companies": [parent companies or manufacturers], '
    '"ingredients": [key ingredients mentioned], '
    '"products": [specific named products mentioned]}.\n'
    "If is_product_related is false, keep the other fields brief or empty."
)


class ArticleSummary(BaseModel):
    is_product_related: bool = False
    category: str = ""
    sentiment: str = "neutral"
    theme: str = ""
    label: str = ""
    summary: str = ""
    event_types: list[str] = Field(default_factory=list)
    importance_score: int = 0
    country: str = ""
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
    def _event_types(value: object) -> list[str]:
        """Normalize event types to the known taxonomy (case-insensitive, deduped)."""
        out: list[str] = []
        for v in MistralSummarizer._as_list(value):
            canon = _EVENT_LOOKUP.get(v.lower())
            if canon and canon not in out:
                out.append(canon)
        return out

    @staticmethod
    def _importance(value: object) -> int:
        try:
            n = int(float(value))
        except (TypeError, ValueError):
            return 0
        return max(1, min(10, n)) if n else 0

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
            event_types=MistralSummarizer._event_types(obj.get("event_types")),
            importance_score=MistralSummarizer._importance(obj.get("importance_score")),
            country=str(obj.get("country") or "").strip(),
            brands=MistralSummarizer._as_list(obj.get("brands")),
            companies=MistralSummarizer._as_list(obj.get("companies")),
            ingredients=MistralSummarizer._as_list(obj.get("ingredients")),
            products=MistralSummarizer._as_list(obj.get("products")),
        )
