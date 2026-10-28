# NewsPulse API Reference

**Base URL:** `https://lionfish-app-ldci4.ondigitalocean.app`

**Platform API Prefix:** `/api/news-pulse`

**Swagger Docs:** `https://lionfish-app-ldci4.ondigitalocean.app/docs`

**Status:** All endpoints tested and working as of 2026-10-28.

---

## System Endpoints

### GET /health

Health check for monitoring.

```
Response: { "status": "ok", "db": "up" }
```

### GET /

App info and version.

```
Response: { "app": "NewsPulse", "version": "0.1.0" }
```

---

## Dashboard & Stats

### GET /api/news-pulse/stats

Returns all dashboard-level statistics in a single call. Use this for the main dashboard widgets (total counts, charts, market coverage).

```
Response:
{
  "total_articles": 3425,
  "total_stories": 2631,
  "total_brands": 4986,
  "total_markets": 16,
  "monthly_history": [
    { "month": "2025-10", "count": 2 },
    { "month": "2025-11", "count": 13 },
    { "month": "2026-10", "count": 1344 }
  ],
  "market_coverage": [
    { "code": "KR", "name": "South Korea", "article_count": 1119, "percentage": 32.7 },
    { "code": "JP", "name": "Japan", "article_count": 697, "percentage": 20.4 },
    { "code": "CN", "name": "China", "article_count": 453, "percentage": 13.2 },
    { "code": "US", "name": "United States", "article_count": 416, "percentage": 12.1 },
    { "code": "IN", "name": "India", "article_count": 309, "percentage": 9.0 },
    { "code": "TH", "name": "Thailand", "article_count": 159, "percentage": 4.6 },
    { "code": "GB", "name": "United Kingdom", "article_count": 158, "percentage": 4.6 }
  ],
  "signal_breakdown": {
    "emerging-topic": 517,
    "mainstream": 769,
    "first-mention": 2139
  },
  "avg_importance": 6.6
}
```

**Use for:** Articles Tracked widget, Monthly History chart, Market Coverage chart, Signal Tier breakdown.

---

## Articles

### GET /api/news-pulse/articles

Returns all articles. Supports filtering and pagination.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `market` | string | — | Filter by market code (KR, JP, CN, US, IN, TH, GB, etc.) |
| `brand` | string | — | Filter by brand slug |
| `signal` | string | — | Filter by signal_tier (first-mention, emerging-topic, mainstream) |
| `event_type` | string | — | Filter by event type (Partnership, Launch, Expansion, etc.) |
| `story` | string | — | Filter by story_id (group of related articles) |
| `q` | string | — | Search in headline and summary |
| `sort` | string | `recent` | Sort order: `recent`, `importance`, `velocity` |
| `page` | int | 1 | Page number (only used with page_size) |
| `page_size` | int | all | Results per page; omit to get all articles |

**Response:**

```json
{
  "articles": [
    {
      "id": "uuid",
      "slug": "article-slug-abc123",
      "story_id": "story-12345",
      "headline": "Article headline text",
      "summary": "3-5 sentence summary of the article",
      "source": "beautyindependent.com",
      "source_tier": "tier-1",
      "url": "https://example.com/article",
      "image_url": "https://example.com/image.jpg",
      "market": "South Korea",
      "market_code": "KR",
      "signal_tier": "emerging-topic",
      "topic_velocity": 12.0,
      "importance_score": 8,
      "event_types": ["Launch", "Partnership"],
      "published_at": "2026-10-27T10:30:00Z",
      "brands": [
        { "id": "uuid", "name": "COSRX", "slug": "cosrx-02f435" }
      ],
      "products": [
        { "id": "uuid", "name": "Snail Mucin Essence", "slug": "snail-mucin-essence-abc123" }
      ],
      "companies": [
        { "id": "uuid", "name": "Cosmax", "slug": null }
      ],
      "ingredients": [
        { "id": "uuid", "name": "Snail Mucin", "slug": "snail-mucin-abc123" }
      ]
    }
  ],
  "total": 3425,
  "page": 1,
  "page_size": 3425
}
```

**Examples:**

```
# Get all articles (no limit)
GET /api/news-pulse/articles

# Get first 50 articles
GET /api/news-pulse/articles?page_size=50

# Page 2 of 50-per-page
GET /api/news-pulse/articles?page_size=50&page=2

# Filter by market
GET /api/news-pulse/articles?market=KR

# Filter by brand
GET /api/news-pulse/articles?brand=cosrx-02f435

# Search
GET /api/news-pulse/articles?q=retinol

# Sort by importance
GET /api/news-pulse/articles?sort=importance

# Combined filters
GET /api/news-pulse/articles?market=JP&signal=emerging-topic&sort=importance&page_size=20
```

### GET /api/news-pulse/articles/{slug}

Returns a single article by its slug.

```
GET /api/news-pulse/articles/k-beauty-direct-selling-market-faces-690719

Response: { ...single article object (same shape as list item)... }

Error: 404 { "detail": "article not found" }
```

---

## Brands

### GET /api/news-pulse/brands

Returns all brands with article counts, sorted by most mentioned.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `min_articles` | int | 0 | Only return brands with at least this many articles |

**Response:**

```json
[
  { "id": "uuid", "name": "medicube", "slug": "medicube-b7a39e", "article_count": 223 },
  { "id": "uuid", "name": "Beauty of Joseon", "slug": "beauty-of-joseon-61a4b3", "article_count": 168 },
  { "id": "uuid", "name": "Anua", "slug": "anua-d95af9", "article_count": 156 },
  { "id": "uuid", "name": "COSRX", "slug": "cosrx-02f435", "article_count": 138 }
]
```

**Examples:**

```
# All brands
GET /api/news-pulse/brands

# Only brands with 10+ articles
GET /api/news-pulse/brands?min_articles=10
```

---

## Markets

### GET /api/news-pulse/markets

Returns all markets with article counts, sorted by most articles.

**Response:**

```json
[
  { "code": "KR", "name": "South Korea", "article_count": 1119 },
  { "code": "JP", "name": "Japan", "article_count": 697 },
  { "code": "CN", "name": "China", "article_count": 453 },
  { "code": "US", "name": "United States", "article_count": 416 },
  { "code": "IN", "name": "India", "article_count": 309 },
  { "code": "TH", "name": "Thailand", "article_count": 159 },
  { "code": "GB", "name": "United Kingdom", "article_count": 158 }
]
```

---

## Stories

A "story" groups related articles about the same event/topic (e.g. 5 articles about the same product launch).

### GET /api/news-pulse/stories

Returns story clusters, each with its source articles and linked brands.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `brand` | string | — | Filter by brand slug |
| `market` | string | — | Filter by market code |
| `min_sources` | int | 1 | Minimum number of source articles |
| `sort` | string | `importance` | Sort: `importance`, `velocity`, `recent`, `sources` |
| `page` | int | 1 | Page number |
| `page_size` | int | 20 | Results per page (max 100) |

**Response:**

```json
{
  "stories": [
    {
      "story_id": "story-1809",
      "headline": "K-Beauty Glass Skin Routine and Top Products",
      "summary": "Summary of the story...",
      "source_count": 5,
      "signal_tier": "mainstream",
      "importance_score": 9,
      "topic_velocity": 25.0,
      "sources": [
        {
          "headline": "Source article headline",
          "source": "vogue.com",
          "url": "https://...",
          "published_at": "2026-10-27T10:00:00Z"
        }
      ],
      "brands": [
        { "id": "uuid", "name": "COSRX", "slug": "cosrx-02f435" }
      ]
    }
  ],
  "total": 2631,
  "page": 1,
  "page_size": 20
}
```

### GET /api/news-pulse/stories/{story_id}

Returns a single story with all its source articles.

```
GET /api/news-pulse/stories/story-1809

Error: 404 { "detail": "story not found" }
```

---

## Topic Clusters

Topic clusters are AI-generated groupings of articles around a broader theme (e.g. "K-beauty global expansion", "AI in cosmetics").

### GET /api/news-pulse/topics

Returns topic clusters with metadata.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `country` | string | — | Filter by primary_country code |
| `category` | string | — | Filter by primary_category |
| `min_articles` | int | 2 | Minimum article count in cluster |
| `sort` | string | `velocity` | Sort: `velocity`, `articles`, `recent` |
| `page` | int | 1 | Page number |
| `page_size` | int | 20 | Results per page (max 100) |

**Response:**

```json
{
  "clusters": [
    {
      "id": "uuid",
      "name": "K-beauty global dominance and market surge",
      "slug": "k-beauty-s-global-dominance-a4e107",
      "description": "Detailed description of the topic cluster...",
      "article_count": 45,
      "source_count": 30,
      "primary_country": "KR",
      "primary_category": "Market Expansion",
      "is_mixed_country": true,
      "is_mixed_category": false,
      "sentiment": "positive",
      "velocity": 28.5
    }
  ],
  "total": 134,
  "page": 1,
  "page_size": 20
}
```

### GET /api/news-pulse/topics/{slug}

Returns a single topic cluster with all its member articles (full article objects).

```
GET /api/news-pulse/topics/k-beauty-s-global-dominance-a4e107

Response: { ...topic cluster fields + "articles": [...full article objects...] }

Error: 404 { "detail": "topic cluster not found" }
```

---

## Leads

### POST /api/news-pulse/leads

Create a new lead (newsletter signup, contact form, etc.).

**Request Body:**

```json
{
  "email": "user@example.com",
  "name": "Jane Doe",
  "company": "Beauty Corp",
  "job_title": "Brand Manager",
  "country_interest": "KR",
  "source": "news-pulse",
  "utm_source": "google",
  "utm_medium": "cpc",
  "utm_campaign": "summer2026"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `email` | Yes | Must be unique |
| `name` | No | Full name |
| `company` | No | Company name |
| `job_title` | No | Job title |
| `country_interest` | No | Market code (KR, JP, CN, etc.) |
| `source` | Yes | One of: `news-pulse`, `newsletter`, `contact-form`, `agency-site`, `download-report`, `other` |
| `utm_source` | No | UTM tracking |
| `utm_medium` | No | UTM tracking |
| `utm_campaign` | No | UTM tracking |

**Responses:**

```
201 Created: { ...lead object... }
409 Conflict: { "detail": "email already registered" }
400 Bad Request: { "detail": "invalid source; must be one of {...}" }
```

**Note:** Creating a lead automatically syncs the profile to Klaviyo (upsert + list subscribe) in the background. No frontend Klaviyo code needed.

### GET /api/news-pulse/leads

List all leads (admin use).

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | string | — | Filter: pending, confirmed, subscribed, unsubscribed, converted, bounced |
| `source` | string | — | Filter: news-pulse, newsletter, contact-form, agency-site, download-report, other |
| `page` | int | 1 | Page number |
| `page_size` | int | 50 | Results per page (max 200) |

**Response:**

```json
{
  "leads": [
    {
      "id": 23,
      "email": "user@example.com",
      "name": "Jane Doe",
      "company": "Beauty Corp",
      "job_title": "Brand Manager",
      "country_interest": "KR",
      "source": "news-pulse",
      "status": "pending",
      "stripe_customer_id": null,
      "email_tool_id": null,
      "utm_source": "google",
      "utm_medium": "cpc",
      "utm_campaign": "summer2026",
      "created_at": "2026-10-27T16:22:04Z",
      "confirmed_at": null,
      "unsubscribed_at": null,
      "last_email_sent_at": null
    }
  ],
  "total": 23,
  "page": 1,
  "page_size": 50
}
```

### GET /api/news-pulse/leads/{id}

Get a single lead by ID.

```
GET /api/news-pulse/leads/23

Response: { ...lead object... }

Error: 404 { "detail": "lead not found" }
```

### PATCH /api/news-pulse/leads/{id}

Update a lead's status or fields.

**Request Body (all optional):**

```json
{
  "status": "confirmed",
  "stripe_customer_id": "cus_abc123",
  "last_email_sent_at": "2026-10-27T12:00:00Z"
}
```

**Auto-timestamps:**
- Setting status to `"confirmed"` auto-fills `confirmed_at`
- Setting status to `"unsubscribed"` auto-fills `unsubscribed_at`

**Note:** Status updates automatically sync to Klaviyo in the background.

---

## Webhooks

### POST /api/news-pulse/webhooks/klaviyo

Receives Klaviyo webhook events (unsubscribe, subscribe, spam). Updates lead status in the database automatically.

**Headers:** `X-Klaviyo-Webhook-Secret: <secret>` (if configured)

### POST /api/news-pulse/webhooks/lead-event

Receives lead lifecycle events from the frontend (e.g. email confirmation, unsubscribe).

**Request Body:**

```json
{
  "lead_id": 23,
  "email": "user@example.com",
  "event": "confirmed"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `lead_id` | No* | Lead ID |
| `email` | No* | Lead email |
| `event` | Yes | `confirmed` or `unsubscribed` |

*Provide either `lead_id` or `email`.

---

## Field Reference

### Signal Tiers

| Value | Meaning |
|-------|---------|
| `first-mention` | First time this topic appears |
| `emerging-topic` | Growing coverage, multiple sources |
| `mainstream` | Widely covered across many sources |

### Event Types

Common values: `Launch`, `Partnership`, `Expansion`, `Acquisition`, `Regulatory`, `Funding`, `Award`, `Innovation`, `Sustainability`

### Lead Status Lifecycle

```
pending -> confirmed -> subscribed -> unsubscribed
                     -> converted
                     -> bounced
```

### Market Codes

| Code | Market |
|------|--------|
| KR | South Korea |
| JP | Japan |
| CN | China |
| US | United States |
| IN | India |
| TH | Thailand |
| GB | United Kingdom |
| HK | Hong Kong |
| TW | Taiwan |
| ID | Indonesia |
| SG | Singapore |
| FR | France |
| EU | Europe |
| MY | Malaysia |
| AU | Australia |

---

## CORS

Allowed origins:
- `https://www.asiacosmepulse.com`
- `https://asiacosmepulse.com`
- `http://localhost:3000` (non-production only)

Allowed methods: `GET`, `POST`, `PATCH`, `OPTIONS`

---

## Notes for Frontend Developer

1. **No pagination limit on `/articles`** — omit `page_size` to get all articles in one call. Use `page_size` + `page` if you want pagination.
2. **Use `/stats` for dashboard widgets** — total counts, monthly history chart, market coverage chart, signal breakdown. One API call gives everything.
3. **Use `/markets` for market filter dropdowns** — dynamically populated, sorted by article count.
4. **Use `/brands?min_articles=5` for brand filters** — avoids loading 5000+ brands, shows only relevant ones.
5. **Lead creation auto-syncs to Klaviyo** — no frontend Klaviyo SDK needed.
6. **`story_id` groups related articles** — use this to show "X sources covering this story".
7. **All IDs are UUIDs** except lead IDs (integers) and story_ids (strings like "story-12345").
8. **Need a new endpoint?** — request it and we'll build it. Possible additions: `/articles/trending`, `/brands/{slug}`, `/search`, weekly digest endpoint, etc.
