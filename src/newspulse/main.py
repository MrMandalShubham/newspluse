"""FastAPI application entrypoint.

Part 0.1 keeps this deliberately bare — just enough to prove the stack boots.
The real /health endpoint arrives in Part 0.3; data endpoints in Phase 5.
"""

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from newspulse import __version__
from newspulse.api import router
from newspulse.config import settings
from newspulse.db import engine
from newspulse.publish.api import router as news_pulse_router

app = FastAPI(title=settings.app_name, version=__version__)

_CORS_ORIGINS = [
    "https://www.asiacosmepulse.com",
    "https://asiacosmepulse.com",
]
if settings.app_env != "production":
    _CORS_ORIGINS.append("http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Webhook-Secret",
                   "X-Klaviyo-Webhook-Secret"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


app.include_router(router)
app.include_router(news_pulse_router)


@app.get("/")
def root() -> dict[str, str]:
    """Liveness placeholder. Confirms the app is up and config loaded."""
    return {
        "app": settings.app_name,
        "version": __version__,
    }


@app.get("/health")
def health() -> dict[str, str]:
    """Health probe for DigitalOcean.

    Always returns 200 so the app is considered live even before the database
    is reachable; the ``db`` field reports connectivity separately.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "up"
    except Exception:
        db_status = "down"
    return {"status": "ok", "db": db_status}
