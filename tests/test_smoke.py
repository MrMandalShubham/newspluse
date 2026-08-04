"""Part 0.1 smoke test — proves the app imports and config loads."""

from fastapi.testclient import TestClient

from newspulse import __version__
from newspulse.config import get_settings
from newspulse.main import app


def test_config_loads() -> None:
    s = get_settings()
    assert s.app_name == "NewsPulse"
    assert s.app_env in {"local", "staging", "production"}


def test_app_boots() -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["app"] == "NewsPulse"
    assert body["version"] == __version__
