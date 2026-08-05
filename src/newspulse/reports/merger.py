"""Cluster merger — combine multiple same-topic articles into one story (Mistral)."""

import json
from abc import ABC, abstractmethod

import httpx
from pydantic import BaseModel

from newspulse.config import settings
from newspulse.mistral import chat_json

SYSTEM_PROMPT = (
    "You are a beauty-industry editor. Several articles cover the same product or the "
    "same type of news. Merge them into one combined brief. "
    'Return ONLY JSON: {"label": a concise headline for the combined story, '
    '"summary": a 3-5 sentence merged summary that synthesizes all the articles without '
    "repeating, noting where they agree or add different angles}. "
    "Base it only on the provided material."
)


class MergedStory(BaseModel):
    label: str = ""
    summary: str = ""


class ClusterMerger(ABC):
    last_usage: dict | None = None

    @abstractmethod
    def merge(self, members: list[dict]) -> MergedStory:
        """Merge member articles (each {title, summary}) into one story."""


class FakeMerger(ClusterMerger):
    def __init__(self, story: MergedStory) -> None:
        self.story = story

    def merge(self, members: list[dict]) -> MergedStory:
        return self.story


class MistralMerger(ClusterMerger):
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

    def merge(self, members: list[dict]) -> MergedStory:
        body = "\n\n".join(
            f"- {m.get('title') or ''}: {m.get('summary') or ''}" for m in members
        )
        content, usage = chat_json(
            self._client, self.api_key, self.model, SYSTEM_PROMPT, f"ARTICLES:\n{body}"
        )
        self.last_usage = usage
        return self.parse(content)

    @staticmethod
    def parse(content: str) -> MergedStory:
        try:
            obj = json.loads(content)
        except json.JSONDecodeError:
            return MergedStory()
        if not isinstance(obj, dict):
            return MergedStory()
        return MergedStory(
            label=str(obj.get("label") or "").strip(),
            summary=str(obj.get("summary") or "").strip(),
        )
