# Bolt Prompt: Leads Capture System for AsiaCosmePulse

## Context

We have a `leads` table in our DigitalOcean platform database (`defaultdb`) and a REST API already serving it at `/api/news-pulse/leads`. The leads system captures everyone who signs up for the weekly digest, downloads a report, submits a contact form, or expresses interest in Asia Cosme Pulse. You need to build the frontend forms that POST to this API and an admin view to manage leads.

---

## API Reference

Base URL: `https://lionfish-app-ldci4.ondigitalocean.app/api/news-pulse`

### POST /api/news-pulse/leads — Create a Lead

This is what every form calls on submit.

```json
// Request body
{
  "email": "user@example.com",        // required, must be unique
  "name": "Jane Doe",                 // optional
  "company": "Beauty Corp",           // optional
  "job_title": "Brand Manager",       // optional
  "country_interest": "KR",           // optional — use market codes below
  "source": "news-pulse",             // required — see valid sources below
  "utm_source": "google",             // optional — from URL params
  "utm_medium": "cpc",                // optional — from URL params
  "utm_campaign": "summer2026"        // optional — from URL params
}

// Success: 201 Created
{
  "id": 1,
  "email": "user@example.com",
  "name": "Jane Doe",
  "company": "Beauty Corp",
  "job_title": "Brand Manager",
  "country_interest": "KR",
  "source": "news-pulse",
  "status": "pending",
  "stripe_customer_id": null,
  "utm_source": "google",
  "utm_medium": "cpc",
  "utm_campaign": "summer2026",
  "created_at": "2026-10-05T08:30:00Z",
  "confirmed_at": null,
  "unsubscribed_at": null,
  "last_email_sent_at": null
}

// Error: 409 Conflict
{ "detail": "email already registered" }

// Error: 400 Bad Request
{ "detail": "invalid source; must be one of {...}" }
```

### GET /api/news-pulse/leads — List Leads (Admin)

```
GET /api/news-pulse/leads?status=pending&source=news-pulse&page=1&page_size=50

Response: {
  "leads": [ ...lead objects... ],
  "total": 142,
  "page": 1,
  "page_size": 50
}
```

Query params:
- `status` — filter by status (pending, confirmed, subscribed, unsubscribed, converted, bounced)
- `source` — filter by source (news-pulse, newsletter, contact-form, agency-site, download-report, other)
- `page` — page number (default 1)
- `page_size` — results per page (default 50, max 200)

### GET /api/news-pulse/leads/{id} — Single Lead

```
GET /api/news-pulse/leads/42

Response: { ...full lead object... }
```

### PATCH /api/news-pulse/leads/{id} — Update Lead

Used by admin dashboard or n8n to update lead status.

```json
// Request body — all fields optional, include only what changes
{
  "status": "confirmed",
  "stripe_customer_id": "cus_abc123",
  "last_email_sent_at": "2026-10-05T12:00:00Z"
}
```

Auto-timestamps:
- Setting `status` to `"confirmed"` → auto-fills `confirmed_at`
- Setting `status` to `"unsubscribed"` → auto-fills `unsubscribed_at`

---

## Valid Sources

Use exactly these strings as the `source` field value:

| Source | When to use |
|--------|-------------|
| `news-pulse` | Newsletter signup on the /news-pulse page |
| `newsletter` | General newsletter signup on any other page |
| `contact-form` | Contact page form submission |
| `agency-site` | Agency/services page inquiry |
| `download-report` | Report download gated form |
| `other` | Fallback for anything else |

---

## Lead Status Lifecycle

```
pending → confirmed → subscribed → unsubscribed
                   ↘ converted
                   ↘ bounced
```

| Status | Meaning |
|--------|---------|
| `pending` | Just submitted the form, not yet confirmed |
| `confirmed` | Clicked double opt-in link (if using double opt-in) |
| `subscribed` | Synced to Klaviyo by n8n, actively receiving emails |
| `unsubscribed` | Opted out of emails |
| `converted` | Became a paying customer |
| `bounced` | Email address bounced |

The frontend only ever creates leads with `status = "pending"`. All status transitions happen server-side (n8n or admin).

---

## Markets for country_interest

Use these codes in the `country_interest` field and as dropdown options:

| Code | Market |
|------|--------|
| KR | South Korea |
| JP | Japan |
| CN | China |
| IN | India |
| TH | Thailand |
| TW | Taiwan |
| US | United States |
| GB | United Kingdom |
| HK | Hong Kong |
| ID | Indonesia |

---

## What to Build

### 1. Newsletter Signup — on /news-pulse page

A compact inline form for the free weekly beauty intelligence digest.

**Fields:**
- Email (required, text input with email type)
- Name (optional, text input)
- Market interest (optional, dropdown of markets above)

**Behavior:**
- Set `source` to `"news-pulse"` automatically
- Capture UTM params from the current URL (see UTM section below)
- POST to `/api/news-pulse/leads`
- On 201: show success — "You're in! Check your inbox for this week's digest."
- On 409: show friendly — "This email is already subscribed."
- On 400/500: show error — "Something went wrong. Please try again."
- Loading state on button while request is in flight
- Clear form on success

**Design:** Minimal — one row with email input + button. Optional expandable section for name and market. Should feel like a natural part of the /news-pulse page, not a separate section.

### 2. Contact Form — on /contact page

A professional inquiry form for brands and agencies.

**Fields:**
- Email (required)
- Name (required)
- Company (required)
- Job title (optional)
- Market interest (optional, multi-select of markets)
- Message (textarea — display only, not sent to leads API; handle separately via email notification or store in a `messages` column if added later)

**Behavior:**
- Set `source` to `"contact-form"`
- Capture UTM params
- POST to `/api/news-pulse/leads` (without message field)
- On 201: show success — "Thank you! We'll be in touch within 24 hours."
- On 409: still show success (they're already a lead, that's fine)
- On error: show error message

**Design:** Clean professional layout. Two-column on desktop (name + email on one row, company + job title on second row), single column on mobile. Market interest as pill/chip multi-select.

### 3. Report Download Gate — on report/download pages

A modal form that appears when user clicks "Download Report" button.

**Fields:**
- Email (required)
- Name (required)
- Company (optional)

**Behavior:**
- Set `source` to `"download-report"`
- Capture UTM params
- POST to `/api/news-pulse/leads`
- On 201: close modal, trigger the PDF download
- On 409: close modal, still trigger the download (they're already captured)
- On error: show inline error, keep modal open

**Design:** Centered modal overlay. Short and clean — three fields max. "Download" button at bottom. Close/X to dismiss without downloading.

### 4. Admin Leads Dashboard — on /admin/leads (protected route)

A management view for all captured leads. Behind authentication.

**Layout:**
- Top bar: filter dropdowns for Status and Source, search by email
- Main area: data table with columns:
  - Email
  - Name
  - Company
  - Source (as colored badge: blue for news-pulse, green for newsletter, orange for contact-form, etc.)
  - Status (as colored badge: gray=pending, blue=confirmed, green=subscribed, red=unsubscribed, gold=converted)
  - Country Interest
  - Created At (relative time — "2 hours ago", "3 days ago")
- Pagination at bottom
- Click a row → slide-out panel showing full lead detail including UTM data and all timestamps

**Data fetching:**
- Default: `GET /api/news-pulse/leads?page=1&page_size=50`
- With filters: `GET /api/news-pulse/leads?status=pending&source=news-pulse&page=1`
- Single lead: `GET /api/news-pulse/leads/{id}`

**Actions:**
- Status change: dropdown on the detail panel to update status via `PATCH /api/news-pulse/leads/{id}`
- Export: optional CSV download of current filtered view (client-side from fetched data)

**Stats bar at top (compute client-side from fetched data or add a /stats endpoint later):**
- Total leads count
- Leads this week
- By status breakdown (pending / subscribed / unsubscribed)
- By source breakdown

---

## UTM Tracking

On every page with a form, automatically read UTM parameters from the URL and include them in the POST body. This tracks where leads come from (Google Ads, social campaigns, etc.).

```javascript
function getUtmParams() {
  const params = new URLSearchParams(window.location.search);
  return {
    utm_source: params.get('utm_source') || undefined,
    utm_medium: params.get('utm_medium') || undefined,
    utm_campaign: params.get('utm_campaign') || undefined,
  };
}

// Usage in form submit
async function submitLead(formData) {
  const utm = getUtmParams();
  const response = await fetch('https://lionfish-app-ldci4.ondigitalocean.app/api/news-pulse/leads', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...formData,
      ...utm,
      source: 'news-pulse',  // or 'contact-form', 'download-report', etc.
    }),
  });

  if (response.status === 201) {
    // success
  } else if (response.status === 409) {
    // already registered — handle gracefully
  } else {
    // error
  }
}
```

Example URLs that would carry UTM params:
```
https://asiacosmepulse.com/news-pulse?utm_source=google&utm_medium=cpc&utm_campaign=kbeauty2026
https://asiacosmepulse.com/contact?utm_source=linkedin&utm_medium=social
```

---

## Database Schema (for reference — already created)

```sql
CREATE TABLE leads (
  id               bigserial    PRIMARY KEY,
  email            text         NOT NULL UNIQUE,
  name             text,
  company          text,
  job_title        text,
  country_interest text,
  source           text         NOT NULL,
  status           text         NOT NULL DEFAULT 'pending',
  token            text,
  stripe_customer_id text,
  user_id          uuid,
  utm_source       text,
  utm_medium       text,
  utm_campaign     text,
  created_at       timestamptz  NOT NULL DEFAULT now(),
  confirmed_at     timestamptz,
  unsubscribed_at  timestamptz,
  last_email_sent_at timestamptz
);
```

Indexes on: `email` (unique), `status`, `created_at`, `user_id`, `source`.

---

## Summary

| Component | Endpoint | Source Value |
|-----------|----------|-------------|
| Newsletter signup (/news-pulse) | POST /api/news-pulse/leads | `news-pulse` |
| Contact form (/contact) | POST /api/news-pulse/leads | `contact-form` |
| Report download gate | POST /api/news-pulse/leads | `download-report` |
| Admin dashboard (/admin/leads) | GET + PATCH /api/news-pulse/leads | — |

All forms write to the same `leads` table via the same API. The `source` field distinguishes where each lead came from. The backend automatically syncs new leads to Klaviyo for email delivery.
