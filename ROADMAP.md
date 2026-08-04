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
| 1.1 | `base` collector (rate-limit, retry, robots, provenance) | unit tests pass | ⬜ |
| 1.2 | One RSS news source end-to-end → `raw_items` + Spaces | run collector → N items stored with full provenance | ⬜ |
| 1.3 | Dedup via `content_hash` | re-run collector → zero new rows (idempotency) | ⬜ |

## Phase 2 — Enrichment (AI extraction)
*Goal: raw text → structured signals + normalized entities.*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 2.1 | Entity dictionary + alias normalization | aliases resolve to one entity | ⬜ |
| 2.2 | Claude extraction: entities + signal type + sentiment | golden-file test: known articles → expected signals | ⬜ |
| 2.3 | Cost/robustness guards (batching, retry, token caps) | survives malformed input; cost logged | ⬜ |

## Phase 3 — Trend Engine (deterministic)
*Goal: signals → ranked "what's trending."*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 3.1 | Momentum scoring (volume, velocity, breadth, sentiment) | synthetic dataset → exact expected ranking | ⬜ |
| 3.2 | Time windows (7/30-day) + `trends` persistence | recompute is stable & reproducible | ⬜ |

## Phase 4 — Insight Synthesis
*Goal: the sellable Trend Cards.*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 4.1 | Claude Trend Card generation (why + so-what) | output matches JSON schema | ⬜ |
| 4.2 | Citation integrity | every claim cites a real signal/source — no orphans | ⬜ |

## Phase 5 — Delivery (backend only)
*Goal: insights get out.*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 5.1 | FastAPI: `/trends`, `/trends/{id}`, `/report/latest` | contract tests pass | ⬜ |
| 5.2 | Weekly report generator (MD/PDF file) | report file with top-10 cards + citations | ⬜ |

## Phase 6 — Scale & Production on DO
*Goal: it runs itself on DigitalOcean.*

| Part | What | Confirmation Gate | Status |
|---|---|---|---|
| 6.1 | Add retail + regulatory sources | multi-source trends corroborate | ⬜ |
| 6.2 | Scheduler runs full pipeline on cron | unattended run produces a report | ⬜ |
| 6.3 | Deploy to DO + backups + monitoring | runs on DO 7 days, health green, weekly insight delivered | ⬜ |

---

## Working agreement

1. I show you the scope of a Part **before** coding it.
2. You confirm.
3. I build it.
4. We run the Gate together.
5. Green + your OK → mark ✅, move on.
