# NewsPulse — Architecture

> Beauty-product **trend-detection engine**. Scrapes news + retail signals, uses AI to
> detect which products/ingredients/brands are trending and explain *why*, and delivers
> ranked **news insights** to brands and retailers.
>
> A standalone product of AsiaCosmePulse. **No dependency on DIP Engine.**

## Scope

- **Backend + storage only.** No UI / dashboard.
- **Output = news insights**, delivered two ways:
  - **API** (FastAPI, JSON)
  - **Report files** (Markdown / PDF, weekly)
- **Runs on DigitalOcean.** Docker-first so it deploys from day one.
- Built **phase by phase**, each part closed by an automated **confirmation gate**.

## Core concept

The unit of value is a **Trend Card**:

> *"Product / ingredient X is rising in [market], up N% in 30 days, driven by [reason].
> Here's the evidence (cited sources), and here's what you should do."*

## System diagram

```
                          ┌───────────────────────────────────────────────┐
                          │                  NewsPulse Engine               │
                          │                (single Docker stack)            │
  EXTERNAL                │                                                 │
  ┌──────────┐  collect   │  ┌────────────┐   ┌────────────┐  ┌──────────┐ │
  │ RSS /    │──────────► │  │ COLLECTORS │──►│  ENRICH     │─►│  TREND    │ │
  │ News     │            │  │ (workers)  │   │ (Mistral:    │  │  ENGINE   │ │
  │ Retail   │            │  │ provenance │   │  entities + │  │ (scoring, │ │
  │ Reg feeds│            │  │ + dedup    │   │  signals)   │  │  ranking) │ │
  └──────────┘            │  └─────┬──────┘   └─────┬──────┘  └────┬─────┘ │
                          │        │                │              │        │
                          │        ▼                ▼              ▼        │
                          │   ┌─────────────────────────────────────────┐  │
                          │   │            STORAGE LAYER                 │  │
                          │   │  Postgres (structured + pgvector)        │  │
                          │   │  DO Spaces (raw text / html)             │  │
                          │   └─────────────────────────────────────────┘  │
                          │        │                                        │
                          │        ▼                                        │
                          │  ┌────────────┐      ┌──────────────┐           │
                          │  │ SYNTHESIS  │─────►│ DELIVERY      │           │
                          │  │ (Mistral:   │      │ API (FastAPI) │──► JSON   │
                          │  │ TrendCards)│      │ + report gen  │──► PDF/MD │
                          │  └────────────┘      └──────────────┘           │
                          │                                                 │
                          │  SCHEDULER (APScheduler) orchestrates each stage │
                          │  OBSERVABILITY: structured logs + healthcheck    │
                          └───────────────────────────────────────────────┘
```

## Collection framework (config-driven)

Adding a source is **config, not code**. `config/sources.yaml` (the registry) declares each
source; a `GenericCollector` composes a **discovery** strategy (`sitemap | rss | htmlcrawl`)
and an **extraction** strategy (`jsonld | readability`) on top of `BaseCollector`
(rate-limit / retry / robots / provenance). A **fleet runner** collects every source with
per-source error isolation (one broken site never stops the rest). Ready for 100+ sources.

## Pipeline stages

1. **Collectors** — config-driven per source (see above). Enforce rate limits,
   retries, robots checks; write provenance. Dedup via `content_hash`.
2. **Enrichment (Mistral)** — extract entities + signal type + sentiment from raw text →
   `signals`; normalize aliases into `entities`.
3. **Trend engine (deterministic, no AI)** — roll signals into `trends`; score momentum;
   rank. Deterministic = reproducible = defensible to buyers.
4. **Synthesis (Mistral)** — generate Trend Cards (why + so-what) for top trends, with
   mandatory source citations.
5. **Delivery** — FastAPI endpoints + weekly report file generation.

**Every stage is idempotent and re-runnable** — safe to re-run without creating duplicates.

## Key design decisions

| Decision | Choice | Why |
|---|---|---|
| Message broker | **None in MVP.** Scheduled batch jobs over Postgres. | Fewer moving parts = stronger, provable base. Add Redis/queue only if scale demands (Phase 6). |
| Trend scoring | **Deterministic**, not AI. | Reproducible, cheap, explainable to B2B buyers. |
| AI usage | Only extraction + narrative. | Bounded cost, bounded risk. |
| Raw content | Stored in **DO Spaces**, keyed by hash. | Keeps Postgres lean; provenance intact. |
| Legal posture | Store raw internally; expose only snippets + links + our analysis. | Sell insight, not wholesale content. |
| Config | `niche.yaml` drives niche + market + sources. | Swap niche without a rewrite. |
| Collection modes | Per source: one-time **backfill** (date-windowed history) + ongoing **news** (daily fresh). | Trend detection needs a history baseline *and* fresh signal. |

## Tech stack → DigitalOcean

| Layer | Choice | On DO |
|---|---|---|
| Language | Python 3.12 | — |
| API | FastAPI + Uvicorn | container |
| ORM / migrations | SQLAlchemy 2 + Alembic | — |
| DB | Postgres 16 + pgvector | **DO Managed Postgres** |
| Raw store | S3-compatible | **DO Spaces** |
| Scheduling | APScheduler (in-process) | container |
| Scraping | httpx + selectolax; Playwright for JS-heavy sites | container |
| AI | Mistral AI (`mistralai` SDK) | external API |
| Packaging | Docker + docker-compose | **DO Droplet** + **DO Container Registry** |
| Config | Pydantic Settings + `.env` | DO env vars / secrets |
| Tests | pytest + coverage | CI + pre-deploy |
| Lint/format | Ruff | CI |
| Backups | Managed PG auto-backups + pg_dump → Spaces | DO |

**MVP DO shape:** 1 Droplet (2 vCPU / 4 GB) + Managed Postgres + one Spaces bucket.

## Storage model (Postgres)

| Table | Purpose |
|---|---|
| `sources` | Registered sources: name, url, type, region, trust score. |
| `raw_items` | Collected items: metadata, url, published/collected time, `content_hash`, lang. Full text in Spaces. |
| `entities` | Normalized dictionary: brand / product / ingredient / category + aliases. |
| `signals` | Extracted facts: one row per (item, entity, signal_type) with sentiment + weight. |
| `trends` | Computed output: entity + window + momentum score + rank. |
| `trend_cards` | Final synthesized insights + citations. |
| `job_runs` | Audit of every pipeline run (for idempotency + observability). |

## Target market (why insights sell)

- **Brand managers** — competitor launches, ingredient trends, sentiment shifts.
- **Retailers / distributors** — what to stock, what's heating up.
- **Investors / trade bodies** — category momentum, emerging brands.

Buyers are drowning in information; they pay for **filtering + interpretation + "so what."**

## MVP focus

- **Niche:** K-beauty skincare *(swappable via config — confirm before Phase 1)*
- **Market:** South Korea + export demand signals
- Depth over breadth: own one niche before expanding.
