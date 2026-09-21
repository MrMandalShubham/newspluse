# News Pulse — Bolt Dashboard Integration Blueprint

How the Bolt dashboard connects to the News Pulse data in DigitalOcean, what
every table/column means, which dashboard section each value feeds, and
copy-paste Bolt prompts to wire it up.

Two environments:

- **Production** — the live dashboard reads **directly from the DO Postgres**
  (`defaultdb`), read-only.
- **Preview / demo** — Bolt uses **its own built-in database**, seeded with a
  small **copy** of the DO data (last ~4 weeks) so previews are fast and don't
  hit production.

---

## 0. Connection (DigitalOcean Postgres)

| Field | Value |
|---|---|
| Host | `db-pgsql-sgp1-89656-test-do-user-35319419-0.a.db.ondigitalocean.com` |
| Port | `25060` |
| Database | `defaultdb` |
| User | `doadmin` (see recommendation below) |
| SSL mode | `require` (CA certificate needed) |
| Password | **store as a Bolt secret — never hard-code in the repo** |

**Security recommendations (do these before go-live):**

1. **Create a read-only DB user for the dashboard** instead of using `doadmin`.
   The dashboard only ever reads News Pulse data:
   ```sql
   CREATE USER dashboard_ro WITH PASSWORD '<pick-a-strong-password>';
   GRANT CONNECT ON DATABASE defaultdb TO dashboard_ro;
   GRANT USAGE ON SCHEMA public TO dashboard_ro;
   GRANT SELECT ON news_pulse_articles, news_article_brands, news_article_companies,
     news_article_ingredients, news_article_products, markets, brands, companies,
     ingredients, products_master TO dashboard_ro;
   ```
   This means a leaked dashboard credential can't modify or delete anything.
2. **Keep the password in Bolt's secret/env manager**, not in committed code.
3. **SSL is mandatory** — DO rejects non-SSL. Bolt needs the DO CA certificate
   (the `ca-certificate.crt` you already have) configured for the PG client.

---

## 1. Where the articles live

Every news article is one row in **`news_pulse_articles`** (in `defaultdb`).
Its brands / companies / ingredients / products are linked through four junction
tables to the shared catalog tables (the same catalog the other Pulses use).

```
                      news_pulse_articles
                             │ id
        ┌───────────┬────────┼─────────────┬──────────────┐
        │           │        │             │              │
news_article_   news_article_ news_article_  news_article_  market_id ─▶ markets
   brands        companies    ingredients      products
     │              │             │               │
     ▼              ▼             ▼               ▼
   brands        companies    ingredients    products_master
```

Current volume: **1,148 articles**, **2,272 brands**, **1,205 companies**,
**1,683 ingredients**, **6,399 products**, **9 markets**.

---

## 2. `news_pulse_articles` — full column map

Each column, what it holds, and where to use it in the dashboard.

| Column | Type | What's stored | Use in dashboard |
|---|---|---|---|
| `id` | uuid | Primary key | React key; detail-page route |
| `slug` | text | Stable SEO slug `{headline}-{id6}` (live, all rows backfilled) | Public URL `/news-pulse/[slug]` — see §8. Generated once at publish, never regenerated |
| `headline` | text | Article title | **Card title** — link to `url` |
| `summary` | text | **3-5 sentence** summary (what/why/impact), ~570 chars avg | Card body (2-3 lines + "more"); full text on detail |
| `source` | text | Publication name, e.g. "Dallas News", "WWD" | Byline / source chip |
| `source_tier` | text | Credibility tier (currently all `tier-2`) | Small trust badge (optional) |
| `market_id` | uuid → `markets.id` | Which market the news is about | **Market filter** + flag chip (join to `markets`) |
| `category` | text | One of `brand, market, regulatory, ingredient, retail, consumer` | **Category filter** facet |
| `sentiment` | text | `positive, neutral, negative` | Sentiment badge / color |
| `theme` | text | Short topic tag, e.g. "K-beauty market growth in the U.S." | Subtitle under headline |
| `reach` | integer | Reserved (currently null) | Ignore for now |
| `published_at` | timestamptz | True article date | **Date display + WEEKLY grouping** (the client's weekly-report axis) |
| `url` | text | Original article link | **"Read original" ↗** (open new tab); make headline + image clickable |
| `signal_tier` | text | `mainstream, emerging-topic, first-mention` | Optional badge — **see caveat below** |
| `topic_velocity` | double | Cluster-size proxy | **Do NOT surface** — currently skewed (one large cluster); use `importance_score` instead |
| `created_at` | timestamptz | Ingestion time | Admin/debug only |
| `image_url` | text | og:image / JSON-LD image (95% coverage) | **Card thumbnail / hero** — fallback when null |
| `importance_score` | integer | **1-10** impact (hybrid: LLM × corroboration); avg 8.1 | **Primary ranking** — sort, badge, min-filter |
| `event_types` | jsonb | String array of what happened | **Event chips + multi-select filter** |

**`event_types` values:** `Acquisition, M&A, Launch, Regulatory, Retail,
Ingredient, Competitor, Partnership, Expansion, Funding`.

**Caveat — `signal_tier` / `topic_velocity`:** both derive from story
clustering, which currently over-merges into one large cluster. Treat them as
experimental. Rank and prioritize by **`importance_score`**. (This can be tuned
later; the blueprint will be updated if so.)

---

## 3. Junction tables + catalog (the cross-Pulse links)

The junctions are pure many-to-many links (`article_id` + entity id). Join
through them to render entity chips and to link News → the other Pulses.

| Junction | Rows | Links to | Catalog columns you'll use |
|---|---|---|---|
| `news_article_brands` | 5,612 | `brands` | `name`, `name_kr` |
| `news_article_companies` | 2,057 | `companies` | `name` |
| `news_article_ingredients` | 5,629 | `ingredients` | `name` |
| `news_article_products` | 4,794 | `products_master` | `name`, `primary_image_url`, `brand_id`, `price_benchmark_usd`, `market`, `data_source` |

**Catalog tables:**

- **`brands`** — `id, code, name, name_kr`. Render brand chips; `name_kr` gives
  the Korean name for K-beauty. Link a chip to the **Brand Dashboard / Retail Pulse**.
- **`companies`** — `id, name`. Parent companies / manufacturers.
- **`ingredients`** — `id, name`. Link a chip to **Ingredient Pulse**.
- **`products_master`** — the full product catalog (44 columns incl.
  `name, primary_image_url, brand_id, price_benchmark_usd/eur/krw/jpy,
  skin_types, skin_concerns, key_claims, market, data_source`). Link a product
  chip to its **Product page / Retail Pulse**. Note: products created from news
  (not yet in the retail catalog) are tagged `data_source = 'newspulse'`.

- **`markets`** — `id, name, code, region, flag, regulatory_authority`. Names:
  `China, Hong Kong, India, Indonesia, Japan, Korea (Global), South Korea,
  United Kingdom, United States`. Use `flag` + `name` on cards and as the market
  filter.

---

## 4. The weekly report (the client's core ask)

Every article has a real `published_at`, so a "weekly report" is a group-by on
the ISO week — no extra tables needed. Base query:

```sql
SELECT date_trunc('week', published_at)::date AS week_start,
       count(*) AS articles,
       round(avg(importance_score),1) AS avg_importance
FROM news_pulse_articles
WHERE published_at >= now() - interval '6 months'
GROUP BY 1 ORDER BY 1 DESC;
```

For one week's report, filter articles to that week and order by
`importance_score DESC`:

```sql
SELECT * FROM news_pulse_articles
WHERE published_at >= :week_start AND published_at < :week_start + interval '7 days'
ORDER BY importance_score DESC NULLS LAST;
```

Coverage today: **27 dense weekly windows**, late-March → mid-September 2026
(43-116 articles/week). A **Week picker** (or "Last 6 months" timeline) is the
natural top-level control.

---

## 5. Bolt prompts — production (direct DO), one per table

Paste these into Bolt in order. They assume the read-only DB connection from §0
is configured as a Bolt secret/env.

### Prompt A — connect + articles feed
```
Connect the dashboard to our PostgreSQL database (credentials in the app's
secrets: PG_HOST, PG_PORT=25060, PG_DB=defaultdb, PG_USER, PG_PASSWORD, SSL
required with the DO CA cert). This is READ-ONLY — never write to it.

Primary table: news_pulse_articles. Load it for the News Pulse feed. Columns:
id, headline, summary, source, source_tier, market_id, category, sentiment,
theme, published_at, url, image_url, importance_score, event_types (jsonb array),
signal_tier. Parse event_types as a string array.

Render each row as a news card:
- image_url as the cover image (lazy, object-cover; graceful placeholder if null)
- headline linking to url (target=_blank rel=noopener); image also clickable
- summary shown as 2-3 lines with a "more" expander
- badges: importance_score as "Impact N/10" (8-10 red, 5-7 amber, 1-4 gray),
  sentiment color, category label
- event_types as small tag chips
Default sort: importance_score DESC (nulls last). Do NOT use topic_velocity.
```

### Prompt B — markets (filter + flag)
```
Join news_pulse_articles.market_id -> markets.id. Use markets.name and
markets.flag. Add a Market filter (multi-select) built from markets, and show
the flag + market name on each card. Markets present: China, Hong Kong, India,
Indonesia, Japan, Korea (Global), South Korea, United Kingdom, United States.
```

### Prompt C — brands (chips + Brand/Retail Pulse link)
```
Many-to-many: news_article_brands(article_id, brand_id) -> brands(id, name,
name_kr). For each article, render its brands as chips (show name; if name_kr
exists, show it on hover/subtitle).

Brand page eligibility (10-article rule): a brand chip links to its brand hub
/news-pulse/brand/[slug] ONLY if that brand has >= 10 news articles; for brands
with 1-9 articles, link to the country hub instead (and/or show "Coming soon").
Compute the count from news_article_brands (or the news_pulse_brand_counts view
if provided). Currently 96 brands qualify (>=10); 1,870 have 1-9.

Add a Brand filter built from the brands that actually appear in the news.
```

### Prompt D — ingredients (chips + Ingredient Pulse link)
```
Many-to-many: news_article_ingredients(article_id, ingredient_id) ->
ingredients(id, name). Render ingredient chips per article; each links to that
ingredient in Ingredient Pulse. Add an Ingredient filter from ingredients seen
in the news.
```

### Prompt E — products (chips/cards + Product/Retail Pulse link)
```
Many-to-many: news_article_products(article_id, product_id) ->
products_master(id, name, primary_image_url, brand_id, price_benchmark_usd,
market, data_source). Render mentioned products as chips (or small cards with
primary_image_url + name + price_benchmark_usd when present). Each links to the
product page / Retail Pulse. Products tagged data_source='newspulse' are ones
first seen in the news (may lack retail detail) — show them, but you can badge
them "from news".
```

### Prompt F — companies (chips)
```
Many-to-many: news_article_companies(article_id, company_id) ->
companies(id, name). Render company chips per article (parent companies /
manufacturers). Optional Company filter.
```

### Prompt G — weekly report view
```
Add a "Weekly report" view over news_pulse_articles.published_at. Provide a
week picker / 6-month timeline. For the selected ISO week, show that week's
articles ordered by importance_score DESC, plus a header strip with:
article count, average importance, top event_types, and top markets that week.
Group-by SQL: date_trunc('week', published_at).
```

### Prompt H — event-type filter + importance controls
```
Build a multi-select filter from event_types values: Acquisition, M&A, Launch,
Regulatory, Retail, Ingredient, Competitor, Partnership, Expansion, Funding.
Add an importance filter (slider or "8+ / 5+ / all"). Both combine with the
market/brand/ingredient filters. Keep importance_score DESC as the default sort.
```

---

## 6. Bolt prompts — preview/demo (Bolt's own DB, copied subset)

For fast previews, copy a recent slice from DO into Bolt's built-in database and
point the preview build at that. Keep FK integrity by copying only the catalog
rows the copied articles reference.

### Prompt P1 — schema in Bolt's DB
```
In the preview/built-in database, create the same tables and columns as §2/§3
of this blueprint: news_pulse_articles, the four news_article_* junctions, and
markets/brands/companies/ingredients/products_master (only the columns the
dashboard uses is fine). Keep the same names and types so the same UI works
against both databases.
```

### Prompt P2 — seed a 4-week sample from DO
```
One-time seed: copy from the DO database into Bolt's DB:
1. The last 4 weeks of news_pulse_articles (published_at >= now() - 28 days),
   e.g. ~250 rows.
2. Only the markets/brands/companies/ingredients/products_master rows referenced
   by those articles (via the junction tables), so foreign keys resolve.
3. The junction rows for those articles.
Then clear any leftover demo/mock rows. The preview now shows real-but-small
data; production still reads DO live.
```

*(Extraction SQL for the seed is in `scripts/` if you'd rather run it yourself —
ask and I'll generate a ready CSV/SQL dump of the 4-week slice.)*

---

## 7. Suggestions (worth adding)

1. **Rank by `importance_score`, not `topic_velocity`.** Velocity is skewed by
   clustering; importance is clean (1-10, avg 8.1).
2. **Weekly digest header** per week (count / avg importance / top events / top
   markets) — turns the raw feed into an at-a-glance "report".
3. **Cross-Pulse deep links** are the differentiator: every brand/ingredient/
   product chip should link into Retail / Ingredient Pulse. The junction data is
   already there.
4. **Read-only DB user** (§0) before go-live.
5. **Null-image fallback** — 5% of articles have no image; design the placeholder.
6. **De-dup "Korea (Global)" vs "South Korea"** markets in the filter UI (map
   both to one "South Korea" facet) — they're separate rows in `markets`.
7. **Future:** an optional per-week synthesized narrative (one paragraph) if the
   client wants a written weekly report, not just a filtered list — small add on
   our side.

---

# Addendum v2 — responses to Bolt review

Each item below is tagged by **owner**: **[Backend]** = the News Pulse engine
(this repo) provides it; **[Bolt]** = dashboard/frontend logic; **[Separate]** =
a distinct build. Facts verified against the live DB.

## 8. Slug strategy — [Backend]

Slugs must be **permanent and stable**, so they are generated **once at publish
time and stored** in `news_pulse_articles.slug` (not regenerated by the frontend
on every render).

- Format: `{headline-slug}-{id6}` where `id6` = first 6 hex chars of the row id.
- Example: `oshimatsubaki-camellia-oil-j-beauty-a1b2c3`.
- CJK / empty headline fallback: `article-{id6}`.
- Never regenerated on headline edits (the id6 suffix guarantees uniqueness).

Status: **LIVE** — `slug` column added to `news_pulse_articles` and all 1,148
existing rows backfilled; new articles get a slug at publish. Public route:
`/news-pulse/[slug]`. `url` stays the *original publisher* link ("Read
original"); `slug` is our *internal* page.

A read-only helper view is also live: **`news_pulse_brand_counts`**
(`brand_id, name, article_count`) — query it for the 10-article brand rule.

## 9. Public vs private layers — [Bolt]

Routing/rendering is Bolt-owned; documented here for shared context. The data in
this blueprint feeds both.

- **Public (SEO-indexed, no login):** `/news-pulse` (feed), `/news-pulse/[slug]`
  (article, soft paywall after N free views), `/news-pulse/brand/[slug]` (brand
  hubs, 10+ articles only — §Prompt C), `/news-pulse/country/[country]`, `/demo`,
  `/pricing`.
- **Private (login + paid, noindex):** `/dashboard/*` — full archive, brand
  tracking, cross-pulse data.

Same tables; the split is which rows/filters each surface exposes.

## 10. Pipeline health — [Backend] (correcting the review)

The review read "1,148 over 16 weeks ≈ 10/day, pipeline broken." That is a
misreading:

- The 1,148 articles are a **deliberate one-time 6-month historical backfill**
  (27 weekly windows), **not** a daily ingestion rate. It is not evidence of a
  broken pipeline.
- **Filter drop rate is ~30%**, not 50-80%: of ~1,645 raw items, ~1,145 (~70%)
  were kept as product-related; the rest are correctly filtered non-product news.

Real ongoing-cadence work (a separate deploy task, not this blueprint):

- Schedule the existing collectors (`googlenews_run`, webhook `POST /ingest`) to
  run **N×/day on DO** (cron/worker). The runners already exist and are resumable.
- Add more sources to the registry (`config/sources.yaml`) to raise daily volume.
- Prune dead sources.

Target volume (e.g. 200/day) is a scheduling + source-count decision — happy to
set up the DO scheduler as a follow-up.

## 11. Story clustering — [Backend] (FIXED)

Previously `signal_tier`/`topic_velocity` came from single-linkage clustering
that **over-merged** (one cluster absorbed ~1,045 articles). Fixed by switching
to **centroid linkage** at a **0.92** near-duplicate threshold: now **716
clusters, max size 70**, only 4 clusters >20 — genuine "same story" groups. The
LLM merge input is capped so large clusters can't overflow.

The fix is applied in the engine (working DB). The `signal_tier` /
`topic_velocity` values in `defaultdb` will refresh on the **next full publish**;
until then they still show the old skewed numbers, so continue to **rank by
`importance_score`** (always clean).

## 12. Retail Pulse data — [Backend] (corrected counts)

News links to retail via the shared `brands` and `products_master` tables. Actual
retail SKU data in the DB (not the 12,300 cited in the review):

| Table | Rows |
|---|---|
| `oliveyoung_global_products` | 2,087 |
| `cosme_jp_products` | 302 |
| `retail_products` | 2,389 |
| `retail_pulse_shelf_share` | 5,771 |

`products_master` (6,399) breaks down as: **Olive Young Global 2,087, @cosme 302,
newspulse 4,010** (products first seen in the news). A news product chip that
resolves to an Olive Young / @cosme row can deep-link to Retail Pulse; a
`data_source='newspulse'` row is news-only until retail data is attached.

## 13. Market de-duplication — [Bolt] (UI) + [Backend] (data)

Keep `markets` rows separate in the DB for accuracy, but **merge in the UI**:

- `South Korea` = domestic Korean market news/products.
- `Korea (Global)` = Korean brands in the global market (e.g. global Olive Young).
- For users, present **one "South Korea" facet**; map both market ids to it in
  the filter. Don't make users choose.

## 14. Email capture / Klaviyo — [Separate build]

Out of scope for the news engine, but straightforward to add if wanted:

- A `leads` table in Postgres as the source of truth (email, source, consent,
  created_at), populated by a public "Get the Free Weekly Digest" CTA.
- Sync to Klaviyo via an n8n webhook; double opt-in (GDPR); 5-email welcome
  sequence over 14 days.

This is a new component (form endpoint + `leads` table + webhook), separate from
News Pulse ingestion — flag it and we'll scope it on its own.

## 15. Pulse complexity ranking — [Bolt] (strategy note)

For sequencing other Pulses: Regulatory (easiest, structured portals) →
Ingredient (structured DBs: INCI/CosIng) → **News (medium — this engine)** →
Retail (hard, fragmented, partnerships) → Voice (hardest, unstructured, legal
risk).
