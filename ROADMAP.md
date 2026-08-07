# NewsPulse — Roadmap & Confirmation Gates

Built **phase by phase, part by part**. Each Part ships with:

- **(a)** automated pytest(s) encoding the acceptance criteria,
- **(b)** a one-command smoke check you run yourself,
- **(c)** a short "what to verify" note.

**A Part is closed only when its Gate is green AND you confirm.**
**Before coding any Part, the exact scope is shown for your approval first.**

Status legend: ⬜ not started · 🔨 in progress · ✅ done

---

## Phase 0 — Foundation
*Goal: an empty but deployable, tested skeleton.*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 0.1 | Repo scaffold, Docker Compose, config, Ruff | `docker-compose up` boots all services | ✅ (containers up, api + db healthy) |
| 0.2 | DB schema + Alembic migrations | migrations apply clean; rollback works | ✅ (Postgres apply/rollback/re-apply verified, 7 tables) |
| 0.3 | Health endpoint + pytest harness + CI | `/health` = 200; `pytest` green in CI | ✅ (`/health`=200 db:up; ruff+pytest green; CI runs on GitHub push) |

## Phase 1 — Ingestion
*Goal: real data lands, with provenance and no duplicates.*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 1.1 | `base` collector (rate-limit, retry, robots, provenance) | unit tests pass | ✅ (9 tests green, offline via MockTransport) |
| 1.2 | The Established collector (news + backfill modes) → `raw_items` + storage | run collector → beauty articles stored with full provenance | ✅ (live: 2 articles → Postgres, bodies+keywords in storage) |
| 1.3 | Dedup via `content_hash` | re-run collector → zero new rows (idempotency) | ✅ (re-run: inserted=0, skipped=2) |

## Phase 2 — Enrichment (AI extraction)
*Goal: raw text → structured signals + normalized entities.*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 2.1 | Entity dictionary + alias normalization | aliases resolve to one entity | ✅ (4 tests: alias→canonical, case-insensitive get-or-create) |
| 2.2 | Mistral extraction: entities + signal type + sentiment | golden-file test: known articles → expected signals | ✅ (offline tests green; live: 2 articles → 41 signals, 41 entities across brand/product/ingredient/category) |
| 2.3 | Cost/robustness guards (retry, token caps, normalization) | survives malformed input; cost logged | ✅ (hyphen-merge, LLM retry/backoff, per-run token+error logging; live 41→37 entities, tokens logged) |

## Phase 3 — Trend Engine (deterministic)
*Goal: signals → ranked "what's trending."*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 3.1 | Momentum scoring (volume, velocity, breadth, sentiment) | synthetic dataset → exact expected ranking | ✅ (exact scores+ranking asserted) |
| 3.2 | Time windows (7/30-day) + `trends` persistence | recompute is stable & reproducible | ✅ (compute_all writes 7d+30d snapshots, audited) |

## Phase 4 — Insight Synthesis
*Goal: the sellable Trend Cards.*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 4.1 | Mistral Trend Card generation (why + so-what) | output matches JSON schema | ✅ (live: 5 cards, coherent why+so-what, JSON-validated w/ fallback) |
| 4.2 | Citation integrity | every claim cites a real signal/source — no orphans | ✅ (citations built by construction from backing articles; test asserts no orphans) |

## Phase 5 — Delivery (backend only)
*Goal: insights get out.*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 5.1 | FastAPI: `/trends`, `/trends/{id}`, `/cards`, `/report/latest` | contract tests pass | ✅ (5 contract tests; live in container: real JSON from Postgres) |
| 5.2 | Weekly report generator (MD file) | report file with top-10 cards + citations | ✅ (render+write tested; live: 30d-latest.md, 5.5KB, cards+citations) |

## Phase 6 — Generalize Collection (Scale to many sources)
*Goal: adding a source is config, not code — ready for 100+ sites.*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 6.1 | Source registry: `config/sources.yaml` + Pydantic config + loader + sync to `sources` | load/validate sample registry; idempotent DB sync | ✅ (5 tests; live sync to Postgres, idempotent) |
| 6.2 | Discovery strategies: sitemap / rss / htmlcrawl + section filter | each tested offline (MockTransport) | ✅ (4 tests: all 3 strategies + backfill window) |
| 6.3 | Extraction strategies: jsonld / readability (trafilatura) | each tested offline on sample HTML | ✅ (5 tests: jsonld + readability, boilerplate stripped) |
| 6.4 | GenericCollector + fleet runner (per-source error isolation); migrate The Established to config | live fleet run; failing source isolated; The Established ingests identically | ✅ (fleet live via config: dedup-regression; isolation tested; old collector removed) |
| 6.5 | Playwright render layer (`render: playwright`) for JS/SPA sources + `max_articles` cap | render dispatch tested; JS site ingests live | ✅ (3 tests; live: Beauty Journal SPA + Vogue rendered & ingested; per-source isolation proven) |

*Deferred to Phase 7: concurrency across sources + scheduler.*

## Phase 7 — Production on DigitalOcean
*Goal: it runs itself, concurrently, in the cloud.*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 7.1 | Bounded concurrency + enrichment cost/rate controls | parallel fleet run within budget cap | ⬜ |
| 7.2 | Scheduler runs full pipeline on cron | unattended run produces a report | ⬜ |
| 7.3 | Deploy to DO (Droplet + Managed PG + Spaces) + backups + monitoring | runs on DO 7 days, health green, weekly insight delivered | ⬜ |

## Phase 8 — Product-Article Reports (current priority)
*Goal: per-article beauty-product summaries; merge same-product/same-topic articles into combined reports. (Trend engine untouched.)*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 8.1 | Data model: `article_reports` + `report_clusters` (+ migration) | migration apply/rollback; models registered | ✅ (SQLite + Postgres verified) |
| 8.2 | Classify + summarize (Mistral: relevance + summary + products); idempotent | offline (fake + parse) + live on a few articles | ✅ (3 tests; live: 27 summarized, 13 product-related / 14 filtered) |
| 8.3 | Embeddings (Mistral) + cosine clustering of same product/topic | synthetic vectors cluster deterministically; live | ✅ (4 tests; live: 13→10 clusters, cross-source & cross-language grouping) |
| 8.4 | Merge clusters (Mistral) + product report (Markdown) + API | report with merged stories + citations; live | ✅ (4 tests; live: 2 merged stories + 8 singletons; /product-report + /product-clusters served) |

## Phase 9 — Webhook / event-driven ingestion (NewsAPI)
*Goal: ingest on new-article events (not daily batch); relevance-gate each; auto-rebuild the product report after N new product articles.*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 9.1 | `ingest_article()` service: dedup → content (provided or fetch+readability) → relevance+summarize → store if product (+embed) | offline: product / not-product / duplicate / fetch | ✅ (5 tests) |
| 9.2 | Secured `POST /ingest` webhook → ingest_article | contract: bad secret 401; good ingests | ✅ (2 tests) |
| 9.3 | NewsAPI adapter + poller runner (`python -m newspulse.feeds.run`) | offline mapping (mock); live needs NEWSAPI_KEY | ✅ (offline; live pending key) |
| 9.4 | Auto-rebuild after N new product articles (`maybe_rebuild`) | rebuilds at threshold, not below | ✅ (covered in 9.1 tests + wired into poller) |

## Phase 10 — Publish to demo dashboard schema (DigitalOcean)
*Goal: final results land in DO in the demo's exact table names/columns so the existing News Pulse dashboard reads them.*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 10.1 | Summarizer emits category/sentiment/theme + typed lists (brands/companies/ingredients/products); store on `article_reports` (+migration) | migration apply/rollback; parse tests | ✅ (migration verified; tests) |
| 10.2 | Demo-schema models + migration: `news_pulse_articles`, 4 junctions, `markets`/`brands`/`companies`/`ingredients`/`products_master` (uuid PKs) | 10 tables migrate/rollback | ✅ (SQLite verified; Postgres pending Docker) |
| 10.3 | Publisher: map product articles → demo tables (get-or-create lookups, upsert by url, junctions; derived source_tier/market/signal_tier/topic_velocity) | offline: mapping + junctions + idempotent | ✅ (2 tests) |
| 10.4 | Live publish to DO + verify demo tables populated | dashboard-shaped rows in Postgres | ⬜ (pending Docker/DO) |

*Assumed defaults (say to change): create demo tables fresh in our DO DB; AI-derive category/sentiment/theme; signal_tier/topic_velocity from cluster size; companies extracted; reach null.*

---

## Working agreement

1. I show you the scope of a Part **before** coding it.
2. You confirm.
3. I build it.
4. We run the Gate together.
5. Green + your OK → mark ✅, move on.
