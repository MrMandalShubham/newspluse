# Bolt Prompt — New Markets Added (Thailand, Taiwan, India expanded)

Copy-paste the prompt below into Bolt to update the dashboard to show all markets dynamically.

**Live API Base URL:** `https://lionfish-app-ldci4.ondigitalocean.app/api/news-pulse`

---

## Prompt

```
We have added 3 new markets to the News Pulse backend. The dashboard's Market Coverage section must now show ALL markets from the database dynamically — not a hardcoded list.

### Live API

Base URL: https://lionfish-app-ldci4.ondigitalocean.app/api/news-pulse

Key endpoints:
- GET /api/news-pulse/markets — returns all markets with article counts
- GET /api/news-pulse/articles?market=KR&limit=20 — articles filtered by market
- GET /api/news-pulse/stories — stories with source articles
- GET /api/news-pulse/topics — topic clusters
- GET /api/news-pulse/brands — brands with article counts

Use these API endpoints to fetch data. Do NOT connect directly to the database.

### What changed in the database

The `news_pulse_articles` table now has articles from 10 markets (was 6-7 before). The `markets` table has the full list. Current counts:

| code | name           | articles | % of total |
|------|----------------|----------|------------|
| KR   | South Korea    | 553      | 45.7%      |
| US   | United States  | 209      | 17.3%      |
| JP   | Japan          | 154      | 12.7%      |
| CN   | China          | 143      | 11.8%      |
| GB   | United Kingdom | 83       | 6.9%       |
| IN   | India          | 46       | 3.8%       |
| TH   | Thailand       | 13       | 1.1%       |
| HK   | Hong Kong      | 4        | 0.3%       |
| TW   | Taiwan         | 3        | 0.2%       |
| ID   | Indonesia      | 3        | 0.2%       |

All junction tables (news_article_brands, news_article_products, etc.) already have links for the new markets. For example Thailand has 40 brand-links and 39 product-links. India has 217 brand-links and 90 product-links.

### What to change in the dashboard

#### 1. Market Coverage widget — query ALL markets dynamically

Do NOT hardcode market codes. Use this query to get the market list:

```sql
SELECT m.code, m.name, COUNT(a.id) AS article_count,
       ROUND(COUNT(a.id)::numeric / SUM(COUNT(a.id)) OVER () * 100, 1) AS percentage
FROM news_pulse_articles a
JOIN markets m ON a.market_id = m.id
GROUP BY m.code, m.name
ORDER BY article_count DESC;
```

This ensures that when we add more markets in the future (e.g. Malaysia, Philippines, Vietnam), they appear automatically without any code change.

#### 2. Market filter / facets

If you have a market filter dropdown or facet chips anywhere in the dashboard, populate it from the same dynamic query above. Do not maintain a static list of markets.

#### 3. Country flag emojis

Map these market codes to flag emojis in the frontend:

```javascript
const MARKET_FLAGS = {
  KR: "🇰🇷", US: "🇺🇸", JP: "🇯🇵", CN: "🇨🇳", GB: "🇬🇧",
  IN: "🇮🇳", TH: "🇹🇭", HK: "🇭🇰", TW: "🇹🇼", ID: "🇮🇩",
  // add more as needed — or derive from code with a flag-emoji library
};
```

#### 4. Article cards for new markets

Articles from TH/TW/IN have the same structure as existing markets:
- `headline`, `summary` (3-5 sentences), `source_name`, `source_url`
- `image_url` for the hero image
- `slug` for SEO-friendly URLs (e.g. `/article/thai-beauty-brand-expands-globally-a1b2c3`)
- `importance_score` (1-10), `event_types` (JSON array), `signal_tier` (HOT/WARM/WATCH/NOISE)
- `topic_velocity` (how many articles cover the same story)
- Linked to brands, products, companies, ingredients via the same junction tables

No special handling needed — they work exactly like KR/JP/CN articles.

#### 5. Weekly report section

If you have a "This Week" or weekly report view, the new markets will appear automatically if your query groups by `market_id` or joins `markets`. The query from the blueprint still works:

```sql
SELECT DATE_TRUNC('week', a.published_at) AS week,
       m.name AS market,
       COUNT(*) AS articles
FROM news_pulse_articles a
JOIN markets m ON a.market_id = m.id
GROUP BY week, m.name
ORDER BY week DESC, articles DESC;
```

#### 6. Do NOT

- Do NOT hardcode a list of market codes anywhere — always query from the database
- Do NOT filter out markets with low article counts — show all of them
- Do NOT recompute importance_score or signal_tier — these come pre-computed from the backend
- Do NOT create separate page templates for new markets — the same article card/layout works for all markets
```

---
