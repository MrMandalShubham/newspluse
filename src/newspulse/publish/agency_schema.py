"""Create the agency schema and tables in the platform DB (defaultdb).

    python -m newspulse.publish.agency_schema

Idempotent: uses IF NOT EXISTS throughout.
"""

from sqlalchemy import create_engine, text

from newspulse.config import settings

DDL = """
-- Schema
CREATE SCHEMA IF NOT EXISTS agency;

-- Trigger function for updated_at
CREATE OR REPLACE FUNCTION agency.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 1. agency_clients
CREATE TABLE IF NOT EXISTS agency.agency_clients (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_code     varchar(50) NOT NULL UNIQUE,
    name            varchar(300) NOT NULL,
    email           varchar(300),
    contact_name    varchar(300),
    phone           varchar(50),
    address         text,
    country         varchar(100),
    vat_number      varchar(100),
    payment_terms   varchar(200),
    status          varchar(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    notion_page_id  varchar(200) UNIQUE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_agency_clients_updated
    ON agency.agency_clients;
CREATE TRIGGER trg_agency_clients_updated
    BEFORE UPDATE ON agency.agency_clients
    FOR EACH ROW EXECUTE FUNCTION agency.set_updated_at();

-- 2. agency_projects
CREATE TABLE IF NOT EXISTS agency.agency_projects (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL
        REFERENCES agency.agency_clients(id) ON DELETE CASCADE,
    name            varchar(500) NOT NULL,
    description     text,
    status          varchar(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'cancelled')),
    start_date      date,
    end_date        date,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_agency_projects_updated
    ON agency.agency_projects;
CREATE TRIGGER trg_agency_projects_updated
    BEFORE UPDATE ON agency.agency_projects
    FOR EACH ROW EXECUTE FUNCTION agency.set_updated_at();

-- 3. agency_reports
CREATE TABLE IF NOT EXISTS agency.agency_reports (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid
        REFERENCES agency.agency_clients(id) ON DELETE SET NULL,
    project_id      uuid
        REFERENCES agency.agency_projects(id) ON DELETE SET NULL,
    title           varchar(500) NOT NULL,
    slug            varchar(300) NOT NULL UNIQUE,
    report_type     varchar(100),
    language        varchar(10) DEFAULT 'en',
    published_at    timestamptz,
    pdf_url         text,
    pdf_hash        varchar(128) UNIQUE,
    status          varchar(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN (
            'draft', 'processing', 'review', 'published', 'archived'
        )),
    visibility      varchar(20) NOT NULL DEFAULT 'public'
        CHECK (visibility IN (
            'public', 'client_specific', 'internal'
        )),
    summary         text,
    extracted_json  jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_agency_reports_updated
    ON agency.agency_reports;
CREATE TRIGGER trg_agency_reports_updated
    BEFORE UPDATE ON agency.agency_reports
    FOR EACH ROW EXECUTE FUNCTION agency.set_updated_at();

-- 4. agency_report_access
CREATE TABLE IF NOT EXISTS agency.agency_report_access (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL
        REFERENCES agency.agency_clients(id) ON DELETE CASCADE,
    report_id       uuid NOT NULL
        REFERENCES agency.agency_reports(id) ON DELETE CASCADE,
    access_type     varchar(20) NOT NULL DEFAULT 'purchased'
        CHECK (access_type IN (
            'purchased', 'trial', 'gifted', 'subscription'
        )),
    granted_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz,
    UNIQUE (client_id, report_id)
);

-- 5. agency_devis
CREATE TABLE IF NOT EXISTS agency.agency_devis (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL
        REFERENCES agency.agency_clients(id) ON DELETE CASCADE,
    project_id      uuid
        REFERENCES agency.agency_projects(id) ON DELETE SET NULL,
    devis_number    varchar(50) NOT NULL UNIQUE,
    title           varchar(500),
    status          varchar(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN (
            'draft', 'sent', 'accepted', 'rejected', 'expired'
        )),
    currency        varchar(10) NOT NULL DEFAULT 'EUR',
    total_ht        numeric(12, 2) DEFAULT 0,
    vat_rate        numeric(5, 2) DEFAULT 20.00,
    total_ttc       numeric(12, 2) DEFAULT 0,
    valid_until     date,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_agency_devis_updated
    ON agency.agency_devis;
CREATE TRIGGER trg_agency_devis_updated
    BEFORE UPDATE ON agency.agency_devis
    FOR EACH ROW EXECUTE FUNCTION agency.set_updated_at();

-- 6. agency_devis_lines
CREATE TABLE IF NOT EXISTS agency.agency_devis_lines (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    devis_id        uuid NOT NULL
        REFERENCES agency.agency_devis(id) ON DELETE CASCADE,
    position        int NOT NULL DEFAULT 0,
    description     text NOT NULL,
    quantity        numeric(10, 2) NOT NULL DEFAULT 1,
    unit_price      numeric(12, 2) NOT NULL DEFAULT 0,
    total           numeric(12, 2) NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- 7. report_brands (junction)
CREATE TABLE IF NOT EXISTS agency.report_brands (
    report_id       uuid NOT NULL
        REFERENCES agency.agency_reports(id) ON DELETE CASCADE,
    brand_id        uuid NOT NULL,
    confidence      numeric(3, 2),
    source_page     int,
    evidence        text,
    PRIMARY KEY (report_id, brand_id)
);

-- 8. report_products (junction)
CREATE TABLE IF NOT EXISTS agency.report_products (
    report_id       uuid NOT NULL
        REFERENCES agency.agency_reports(id) ON DELETE CASCADE,
    product_id      uuid NOT NULL,
    confidence      numeric(3, 2),
    source_page     int,
    evidence        text,
    PRIMARY KEY (report_id, product_id)
);

-- 9. report_ingredients (junction)
CREATE TABLE IF NOT EXISTS agency.report_ingredients (
    report_id       uuid NOT NULL
        REFERENCES agency.agency_reports(id) ON DELETE CASCADE,
    ingredient_id   uuid NOT NULL,
    confidence      numeric(3, 2),
    source_page     int,
    evidence        text,
    PRIMARY KEY (report_id, ingredient_id)
);

-- 10. report_categories (junction)
CREATE TABLE IF NOT EXISTS agency.report_categories (
    report_id       uuid NOT NULL
        REFERENCES agency.agency_reports(id) ON DELETE CASCADE,
    category_id     uuid NOT NULL,
    confidence      numeric(3, 2),
    source_page     int,
    evidence        text,
    PRIMARY KEY (report_id, category_id)
);

-- 11. report_themes (junction)
CREATE TABLE IF NOT EXISTS agency.report_themes (
    report_id       uuid NOT NULL
        REFERENCES agency.agency_reports(id) ON DELETE CASCADE,
    theme_id        uuid NOT NULL,
    confidence      numeric(3, 2),
    source_page     int,
    evidence        text,
    PRIMARY KEY (report_id, theme_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS ix_agency_reports_status_pub
    ON agency.agency_reports(status, published_at DESC);
CREATE INDEX IF NOT EXISTS ix_agency_reports_visibility_pub
    ON agency.agency_reports(visibility)
    WHERE status = 'published';
CREATE INDEX IF NOT EXISTS ix_agency_report_access_client
    ON agency.agency_report_access(client_id);
CREATE INDEX IF NOT EXISTS ix_agency_report_access_report
    ON agency.agency_report_access(report_id);
CREATE INDEX IF NOT EXISTS ix_report_themes_theme
    ON agency.report_themes(theme_id);
CREATE INDEX IF NOT EXISTS ix_report_brands_brand
    ON agency.report_brands(brand_id);
CREATE INDEX IF NOT EXISTS ix_report_products_product
    ON agency.report_products(product_id);
CREATE INDEX IF NOT EXISTS ix_report_ingredients_ingredient
    ON agency.report_ingredients(ingredient_id);
"""


def _split_statements(ddl: str) -> list[str]:
    """Split DDL on semicolons, respecting $$ blocks."""
    parts: list[str] = []
    buf = ""
    in_dollar = False
    for line in ddl.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        if "$$" in line:
            in_dollar = not in_dollar
        buf += line + "\n"
        if not in_dollar and stripped.endswith(";"):
            s = buf.strip().rstrip(";").strip()
            if s:
                parts.append(s)
            buf = ""
    if buf.strip():
        s = buf.strip().rstrip(";").strip()
        if s:
            parts.append(s)
    return parts


def create_agency_schema() -> dict:
    plat = create_engine(settings.publish_database_url)
    try:
        with plat.begin() as conn:
            for stmt in _split_statements(DDL):
                conn.execute(text(stmt))

        with plat.connect() as conn:
            tables = conn.execute(text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'agency' ORDER BY tablename"
            )).fetchall()
            indexes = conn.execute(text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'agency' ORDER BY indexname"
            )).fetchall()
            triggers = conn.execute(text(
                "SELECT tgname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'agency' "
                "AND NOT t.tgisinternal "
                "ORDER BY tgname"
            )).fetchall()

        return {
            "tables": [r.tablename for r in tables],
            "indexes": [r.indexname for r in indexes],
            "triggers": [r.tgname for r in triggers],
        }
    finally:
        plat.dispose()


def main() -> None:
    result = create_agency_schema()
    print(f"[agency_schema] Tables: {result['tables']}")
    print(f"[agency_schema] Indexes: {result['indexes']}")
    print(f"[agency_schema] Triggers: {result['triggers']}")


if __name__ == "__main__":
    main()
