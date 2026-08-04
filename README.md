# NewsPulse

Beauty-product **trend-detection engine**. Scrapes news + retail signals, uses AI to
detect which products/ingredients/brands are trending and explain *why*, and delivers
ranked **news insights** via API and weekly report files.

Standalone product of AsiaCosmePulse. Backend + storage only.

- Architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- Roadmap & confirmation gates: [ROADMAP.md](ROADMAP.md)

## Requirements

- Docker + Docker Compose (to run the stack), **or**
- Python 3.12 (to run tests/app locally without Docker)

## Run with Docker

```bash
cp .env.example .env
docker-compose up --build
```

Then open http://localhost:8000/ — returns app name, version, and env.

## Run locally (no Docker)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    |  macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn newspulse.main:app --reload
```

## Confirmation gate (Part 0.1)

```bash
ruff check .
pytest
```

Both must be green.

## Deploying on DigitalOcean

The same `api` image runs on a DO Droplet. `DATABASE_URL` points at **DO Managed
Postgres** (append `?sslmode=require`); raw content goes to **DO Spaces**. Full deploy
steps land in Phase 6.
