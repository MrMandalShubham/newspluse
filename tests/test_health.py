"""Part 0.3 — health endpoint stays 200 and reports DB status."""

from fastapi.testclient import TestClient

from newspulse.main import app

client = TestClient(app)


def test_health_is_ok() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] in {"up", "down"}
