"""Embedder — turn article summaries into vectors (Mistral) for clustering."""

from abc import ABC, abstractmethod

import httpx

from newspulse.config import settings
from newspulse.mistral import embed_texts


class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


class FakeEmbedder(Embedder):
    """Maps each text to a preset vector. Used in tests."""

    def __init__(self, mapping: dict[str, list[float]]) -> None:
        self.mapping = mapping

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.mapping[t] for t in texts]


class MistralEmbedder(Embedder):
    model = "mistral-embed"

    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self.api_key = api_key or settings.mistral_api_key
        self._client = client or httpx.Client(timeout=60.0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return embed_texts(self._client, self.api_key, texts, self.model)
