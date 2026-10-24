"""Load sources from the client's CSV into the sources table.

    python -m newspulse.feeds.load_sources path/to/site_query_list.csv
"""

import argparse
import csv

from sqlalchemy import select
from sqlalchemy.orm import Session

from newspulse.db import SessionLocal
from newspulse.models import Source

RSS_FEEDS: dict[str, str] = {
    "wwd.com": "https://wwd.com/feed",
    "cosmeticsbusiness.com": "https://www.cosmeticsbusiness.com/rss",
    "globalcosmeticsnews.com": "https://www.globalcosmeticsnews.com/feed",
    "wwdjapan.com": "https://www.wwdjapan.com/feed",
    "kokusaishogyo.co.jp": "https://kokusaishogyo.co.jp/rss/news/",
    "kokusaishogyo-online.jp": "https://kokusaishogyo-online.jp/feed",
    "hankyung.com": "https://www.hankyung.com/feed/all-news",
    "andpremium.jp": "https://andpremium.jp/feed/",
    "prtimes.jp": "https://prtimes.jp/index.rdf",
    "glowonline.jp": "https://glowonline.jp/?feed=all",
    "beautynury.com": "https://www.beautynury.com/rss",
    "jangup.com": "https://www.jangup.com/rss/allArticle.xml",
    "vogue.co.jp": "https://www.vogue.co.jp/feed/rss",
    "fashionsnap.com": "https://www.fashionsnap.com/rss.xml",
}

SKIP_DOMAINS = {
    "blog.naver.com",
    "powderroom.co.kr",
    "glowpick.com",
}


def _normalize_url(raw: str) -> str:
    url = raw.strip().rstrip("/")
    if url.startswith("http"):
        return url
    return f"https://{url}"


def _domain_key(url: str) -> str:
    """Extract a short domain key for matching RSS feeds."""
    clean = url.replace("https://", "").replace("http://", "").replace("www.", "")
    return clean.split("/")[0]


def _classify(url: str, domain: str) -> str:
    """Determine scraper_class based on known RSS feeds or default to google_news."""
    for rss_domain in RSS_FEEDS:
        if rss_domain in domain:
            return "rss"
    return "google_news"


def fix_rss_sources(session: Session | None = None) -> dict:
    """Re-classify sources that have known RSS feeds but are set to google_news."""
    own_session = session is None
    session = session or SessionLocal()
    fixed = 0

    for domain, feed_url in RSS_FEEDS.items():
        sources = session.execute(
            select(Source).where(
                Source.name.contains(domain),
                Source.scraper_class != "rss",
            )
        ).scalars().all()

        for src in sources:
            src.scraper_class = "rss"
            src.feed_url = feed_url
            src.enabled = True
            fixed += 1

    session.commit()
    if own_session:
        session.close()

    if fixed:
        print(f"[fix_rss] Reclassified {fixed} sources to RSS", flush=True)
    return {"fixed": fixed}


def load_sources_from_csv(csv_path: str, session: Session | None = None) -> dict:
    own_session = session is None
    session = session or SessionLocal()

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    url_col = list(rows[0].keys())[0]
    created = 0
    updated = 0
    skipped = 0

    for row in rows:
        raw_url = row[url_col].strip()
        if not raw_url:
            continue

        url = _normalize_url(raw_url)
        domain = _domain_key(url)

        if domain in SKIP_DOMAINS:
            skipped += 1
            continue

        gl = (row.get("gl") or "").strip().lower() or None
        hl = (row.get("hl") or "").strip().lower() or None
        country = (row.get("country") or "").strip() or None
        query = (row.get("query") or "").strip() or None
        scraper_class = _classify(url, domain)

        name = domain
        if "/" in url.replace("https://", "").replace("http://", "").replace("www.", ""):
            path = url.replace("https://", "").replace("http://", "").replace("www.", "")
            parts = path.split("/", 1)
            if len(parts) > 1 and parts[1]:
                name = f"{parts[0]}/{parts[1][:30]}"

        existing = session.execute(
            select(Source).where(Source.name == name)
        ).scalar_one_or_none()

        if existing:
            existing.scraper_class = scraper_class
            existing.query = query
            existing.gl = gl
            existing.hl = hl
            existing.enabled = True
            if scraper_class == "rss":
                existing.feed_url = RSS_FEEDS.get(domain)
            updated += 1
        else:
            try:
                src = Source(
                    name=name,
                    url=url,
                    type="news",
                    region=country or gl,
                    scraper_class=scraper_class,
                    feed_url=RSS_FEEDS.get(domain),
                    query=query,
                    gl=gl,
                    hl=hl,
                    enabled=True,
                )
                session.add(src)
                session.flush()
                created += 1
            except Exception:
                session.rollback()
                skipped += 1

    session.commit()
    if own_session:
        session.close()

    result = {"created": created, "updated": updated, "skipped": skipped, "total": len(rows)}
    print(f"[load_sources] {result}")
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Load sources from CSV.")
    parser.add_argument("csv_path", help="Path to site_query_list.csv")
    args = parser.parse_args(argv)
    load_sources_from_csv(args.csv_path)


if __name__ == "__main__":
    main()
