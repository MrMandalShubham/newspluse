-- Leads table for AsiaCosmePulse — lead capture + email marketing pipeline
-- Target: DigitalOcean defaultdb (or newspulse), public schema
-- Run once to create. Safe to re-run (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS leads (
  id          bigserial    PRIMARY KEY,
  email       text         NOT NULL UNIQUE,
  name        text,
  company     text,
  job_title   text,
  country_interest text,
  source      text         NOT NULL,
  status      text         NOT NULL DEFAULT 'pending',
  token       text,
  stripe_customer_id text,
  user_id     uuid,
  utm_source  text,
  utm_medium  text,
  utm_campaign text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  confirmed_at     timestamptz,
  unsubscribed_at  timestamptz,
  last_email_sent_at timestamptz,

  CONSTRAINT leads_source_check CHECK (source IN (
    'news-pulse', 'newsletter', 'contact-form',
    'agency-site', 'download-report', 'other'
  )),
  CONSTRAINT leads_status_check CHECK (status IN (
    'pending', 'confirmed', 'subscribed',
    'unsubscribed', 'converted', 'bounced'
  ))
);

CREATE INDEX IF NOT EXISTS idx_leads_status     ON leads (status);
CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_user_id    ON leads (user_id);
CREATE INDEX IF NOT EXISTS idx_leads_source     ON leads (source);
