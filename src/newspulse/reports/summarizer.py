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

CATEGORIES = {
    "brand", "market", "regulatory", "ingredient",
    "retail", "consumer", "lifestyle", "fragrance",
}
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
    "FIRST QUESTION: Is this article relevant to beauty, cosmetics, skincare, self-care, "
    "personal care, haircare, fragrance/perfume, body care, wellness, spa, nail care, "
    "makeup, or the broader beauty lifestyle?\n"
    "CLASSIFY AS TRUE (is_product_related) if the article covers ANY of these:\n"
    "- Product launches, reviews, recommendations, or beauty tips/tutorials\n"
    "- Brand news, company earnings, or business moves by beauty/cosmetics companies\n"
    "- M&A/acquisitions involving beauty or personal care companies\n"
    "- Ingredient trends, formulation science, or cosmetic chemistry\n"
    "- Regulatory changes (cosmetics/MFDS/NMPA/PMDA)\n"
    "- Retail expansion or beauty retail (Olive Young, Sephora, @cosme)\n"
    "- K-beauty, J-beauty, C-beauty trends, or regional beauty culture\n"
    "- OEM/ODM manufacturers (Cosmax, Kolmar, Intercos)\n"
    "- Packaging, beauty-tech, beauty e-commerce, or DTC beauty brands\n"
    "- Self-care routines, wellness trends connected to beauty\n"
    "- Fragrance/perfume industry news, scent trends, aromatherapy\n"
    "- Celebrity or influencer beauty collaborations, beauty content creators\n"
    "- Dermatology or aesthetic treatments (non-surgical: Botox, fillers, lasers)\n"
    "- Sustainability, clean beauty, or eco-packaging in cosmetics\n"
    "- Beauty awards, rankings, or consumer surveys about beauty products\n"
    "When in doubt, lean toward TRUE — we prefer to include borderline beauty content "
    "rather than miss it.\n\n"
    "CLASSIFY AS FALSE only if the article is clearly unrelated:\n"
    "- Pure politics, real estate, automotive, food/beverage (no beauty angle)\n"
    "- Tech/smartphones, general trade/shipping, sports\n"
    "- Pure celebrity gossip with zero beauty/product connection\n"
    "- Pharma/medical treatments for diseases (NOT cosmeceutical or aesthetic)\n\n"
    "CLASSIFICATION EXAMPLES:\n"
    'Title: "L\'Oreal Reports Q3 Earnings Beat" -> true\n'
    'Title: "Shiseido Launches New Anti-Aging Serum in Japan" -> true\n'
    'Title: "MFDS Updates Sunscreen Filter Regulations" -> true\n'
    'Title: "Amorepacific Acquires Stake in K-Beauty Startup" -> true\n'
    'Title: "PDRN Emerges as Viral Anti-Aging Ingredient" -> true\n'
    'Title: "10 Best Moisturizers for Dry Winter Skin" -> true\n'
    'Title: "The Rise of Quiet Luxury in Fragrance" -> true\n'
    'Title: "How to Build a Self-Care Routine" -> true\n'
    'Title: "Japanese Beauty Trends to Watch in 2026" -> true\n'
    'Title: "Vogue Picks: Best New Perfumes This Month" -> true\n'
    'Title: "Shipping Container Prices Rise 12% in Q3" -> false\n'
    'Title: "Real Estate Prices in Seoul Decline" -> false\n'
    'Title: "Celebrity Divorce Announcement" -> false\n'
    'Title: "Tech Company Launches New Smartphone" -> false\n'
    'Title: "Hospital Reports New Cancer Treatment" -> false\n\n'
    "After classifying, extract structured fields. Return ONLY JSON:\n"
    '{"is_product_related": true/false, '
    '"category": one of ["brand","market","regulatory","ingredient",'
    '"retail","consumer","lifestyle","fragrance"], '
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
