"""Part 9.2 — /ingest webhook: auth + ingestion (offline via overrides)."""

from fastapi.testclient import TestClient

from newspulse.api import get_embedder, get_summarizer
from newspulse.config import settings
from newspulse.db import get_session
from newspulse.main import app
from newspulse.models import ArticleReport
from newspulse.reports.embedder import FakeEmbedder
from newspulse.reports.summarizer import ArticleSummary, FakeSummarizer

PRODUCT = ArticleSummary(
    is_product_related=True, label="Serum guide", summary="A serum guide.", products=["CeraVe"]
)


def _client(db_session) -> TestClient:
    def _session():
        yield db_session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_summarizer] = lambda: FakeSummarizer(PRODUCT)
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder({"A serum guide.": [1.0, 0.0]})
    return TestClient(app)


def test_ingest_webhook_requires_secret(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "webhook_secret", "s3cret")
    client = _client(db_session)
    try:
        resp = client.post(
            "/ingest",
            json={"url": "https://mag.example/a", "content": "beauty serum article"},
            headers={"X-Webhook-Secret": "wrong"},
        )
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_ingest_webhook_accepts_and_ingests(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "webhook_secret", "s3cret")
    client = _client(db_session)
    try:
        resp = client.post(
            "/ingest",
            json={"url": "https://mag.example/a", "content": "beauty serum article",
                  "title": "Serum guide", "source_name": "Mag"},
            headers={"X-Webhook-Secret": "s3cret"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ingested", "product": True}
        assert db_session.query(ArticleReport).count() == 1
    finally:
        app.dependency_overrides.clear()
