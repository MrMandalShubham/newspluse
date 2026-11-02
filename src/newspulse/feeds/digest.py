"""Weekly AI digest — generates an executive report from top articles.

    python -m newspulse.feeds.digest

Queries the platform DB for the week's top articles, sends them to Mistral
for structured analysis, and saves JSON + HTML to object storage.
Designed to run every Monday via GitHub Actions.
"""

import json
import sys
import tempfile
import time
from datetime import date, datetime

import httpx
from sqlalchemy import create_engine, text

from newspulse.config import settings
from newspulse.mistral import chat_json
from newspulse.storage import get_storage

SYSTEM_PROMPT = (
    "You are a beauty-industry intelligence analyst for an Asia-focused cosmetics "
    "market platform. Given a list of this week's top beauty news articles "
    "(pre-sorted by importance), produce a structured weekly digest in JSON.\n\n"
    "Output exactly this JSON structure:\n"
    "{\n"
    '  "executive_summary": "3-5 sentence overview of the week\'s most significant '
    'beauty industry developments across Asian markets.",\n'
    '  "key_takeaways": ["takeaway 1", "takeaway 2", "takeaway 3"],\n'
    '  "categories": {\n'
    '    "MARKET": [\n'
    "      {\n"
    '        "headline": "original headline",\n'
    '        "why_it_matters": "1-2 sentences on business impact",\n'
    '        "market": "country name",\n'
    '        "impact": "HIGH or MEDIUM"\n'
    "      }\n"
    "    ],\n"
    '    "REGULATORY": [...],\n'
    '    "RETAIL": [...],\n'
    '    "BRAND": [...],\n'
    '    "INGREDIENT": [...]\n'
    "  },\n"
    '  "emerging_trends": ["trend 1 observed across markets", "trend 2"]\n'
    "}\n\n"
    "Rules:\n"
    "- Only include categories that have articles. Omit empty categories.\n"
    "- Skip any article not relevant to beauty/cosmetics industry.\n"
    '- "impact" is HIGH for importance_score >= 7, MEDIUM for 4-6.\n'
    '- "why_it_matters" should explain the business significance for beauty '
    "industry executives.\n"
    '- "emerging_trends" identifies patterns across multiple articles or markets.\n'
    "- Keep the executive_summary concise and actionable.\n"
    "- Return valid JSON only, no markdown wrapping."
)


def _week_label() -> str:
    today = date.today()
    return f"{today.isocalendar()[0]}-W{today.isocalendar()[1]:02d}"


def _fetch_top_articles(engine, limit: int = 20) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT a.id, a.headline, a.summary, a.category, a.sentiment, "
            "a.importance_score, a.published_at, a.url, a.event_types, "
            "a.image_url, m.name AS market "
            "FROM news_pulse_articles a "
            "JOIN markets m ON a.market_id = m.id "
            "WHERE a.published_at >= now() - interval '7 days' "
            "AND coalesce(a.importance_score, 0) >= 3 "
            "ORDER BY a.importance_score DESC NULLS LAST, "
            "a.published_at DESC NULLS LAST "
            "LIMIT :lim"
        ), {"lim": limit}).fetchall()
    return [
        {
            "id": r.id,
            "headline": r.headline,
            "summary": r.summary,
            "category": r.category,
            "sentiment": r.sentiment,
            "importance_score": r.importance_score,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "url": r.url,
            "event_types": r.event_types,
            "image_url": r.image_url,
            "market": r.market,
        }
        for r in rows
    ]


def _fetch_related_products(engine, article_ids: list) -> dict:
    """Return {article_id: [{name, brand_name, image_url}]} — max 2 per article."""
    if not article_ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT article_id, name, brand_name, primary_image_url FROM ("
            "  SELECT nap.article_id, p.name, b.name AS brand_name, "
            "    p.primary_image_url, "
            "    row_number() OVER (PARTITION BY nap.article_id ORDER BY "
            "      coalesce(p.data_quality_score,0) DESC, "
            "      p.is_best DESC NULLS LAST) AS rn "
            "  FROM news_article_products nap "
            "  JOIN products_master p ON p.id = nap.product_id "
            "    AND p.data_source IS DISTINCT FROM 'newspulse' "
            "  LEFT JOIN brands b ON b.id = p.brand_id "
            "  WHERE nap.article_id = ANY(:aids)"
            ") t WHERE rn <= 2"
        ), {"aids": article_ids}).fetchall()
    result: dict = {}
    for r in rows:
        result.setdefault(r.article_id, []).append({
            "name": r.name,
            "brand_name": r.brand_name,
            "image_url": r.primary_image_url,
        })
    return result


def _render_html(digest: dict) -> str:
    week = digest.get("week", "")
    lines = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>Beauty Intel Digest - {week}</title>",
        "<style>body{font-family:system-ui,sans-serif;max-width:720px;"
        "margin:2em auto;padding:0 1em;line-height:1.6;color:#333}"
        "h1{color:#d63384}h2{border-bottom:2px solid #f8d7e8;padding-bottom:.3em}"
        ".card{margin:1em 0;padding:1em;background:#fdf2f8;border-radius:8px;"
        "border-left:4px solid #d63384}"
        ".meta{color:#666;font-size:.85em;margin-top:.5em}"
        ".tag{display:inline-block;background:#d63384;color:#fff;padding:2px 8px;"
        "border-radius:4px;font-size:.75em;margin-right:.5em}"
        ".article-img{width:100%;max-height:200px;object-fit:cover;border-radius:6px;"
        "margin-bottom:.8em}"
        ".products{display:flex;gap:.8em;margin-top:.8em;flex-wrap:wrap}"
        ".product{display:flex;align-items:center;gap:.5em;background:#fff;"
        "padding:6px 10px;border-radius:6px;border:1px solid #e8e8e8;font-size:.8em}"
        ".product img{width:40px;height:40px;object-fit:cover;border-radius:4px}"
        ".product-info{line-height:1.3}.product-brand{color:#888;font-size:.85em}"
        "ol,ul{padding-left:1.5em}</style></head><body>",
        f"<h1>Weekly Beauty Intel Digest</h1><p><em>{week}</em></p>",
        f"<h2>Executive Summary</h2><p>{digest.get('executive_summary', '')}</p>",
    ]
    if digest.get("key_takeaways"):
        lines.append("<h2>Key Takeaways</h2><ol>")
        for t in digest["key_takeaways"]:
            lines.append(f"<li>{t}</li>")
        lines.append("</ol>")
    for cat, articles in (digest.get("categories") or {}).items():
        lines.append(f"<h2><span class='tag'>{cat}</span></h2>")
        for a in articles:
            img_url = a.get("image_url") or ""
            img_tag = ""
            if img_url and img_url.startswith(("https://", "http://")):
                img_tag = f"<img class='article-img' src='{img_url}' loading='lazy' alt=''>"
            prod_html = ""
            for p in (a.get("products") or [])[:2]:
                p_img = ""
                p_url = p.get("image_url") or ""
                if p_url and p_url.startswith(("https://", "http://")):
                    p_img = f"<img src='{p_url}' loading='lazy' alt=''>"
                brand = p.get("brand_name") or ""
                brand_span = f"<div class='product-brand'>{brand}</div>" if brand else ""
                prod_html += (
                    f"<div class='product'>{p_img}"
                    f"<div class='product-info'><div>{p['name']}</div>{brand_span}</div>"
                    f"</div>"
                )
            if prod_html:
                prod_html = f"<div class='products'>{prod_html}</div>"
            lines.append(
                f"<div class='card'>{img_tag}<strong>{a['headline']}</strong>"
                f"<p>{a.get('why_it_matters', '')}</p>"
                f"{prod_html}"
                f"<p class='meta'>{a.get('market', '')} &middot; "
                f"Impact: {a.get('impact', '')}</p></div>"
            )
    if digest.get("emerging_trends"):
        lines.append("<h2>Emerging Trends</h2><ul>")
        for t in digest["emerging_trends"]:
            lines.append(f"<li>{t}</li>")
        lines.append("</ul>")
    lines.append("</body></html>")
    return "\n".join(lines)


_CAT_COLORS = {
    "MARKET": "#2563eb",
    "REGULATORY": "#dc2626",
    "RETAIL": "#059669",
    "BRAND": "#7c3aed",
    "INGREDIENT": "#d97706",
}


def _render_premium_html(digest: dict, *, for_pdf: bool = False) -> str:
    """Render the editorial digest. When for_pdf=True, skip external images for small file size."""
    week = digest.get("week", "")
    today = date.today().strftime("%B %d, %Y")
    summary = digest.get("executive_summary", "")

    takeaways_html = ""
    colors = ["#d63384", "#2563eb", "#7c3aed", "#059669"]
    bgs = ["#fdf2f8", "#eff6ff", "#faf5ff", "#ecfdf5"]
    for i, t in enumerate((digest.get("key_takeaways") or [])[:4]):
        c, bg = colors[i % 4], bgs[i % 4]
        takeaways_html += (
            f"<div style='background:{bg};border-radius:10px;padding:20px 24px;"
            f"margin-bottom:12px'>"
            f"<div style='font-family:Georgia,serif;font-size:24px;font-weight:700;"
            f"color:{c};margin-bottom:8px'>{i+1:02d}</div>"
            f"<div style='font-size:14px;line-height:1.6;color:#334155'>{t}</div></div>"
        )

    articles_html = ""
    for cat, items in (digest.get("categories") or {}).items():
        cat_color = _CAT_COLORS.get(cat, "#64748b")
        articles_html += (
            f"<div style='display:flex;align-items:center;gap:10px;margin:32px 0 16px'>"
            f"<span style='background:{cat_color};color:#fff;padding:3px 10px;"
            f"border-radius:5px;font-size:11px;font-weight:700;letter-spacing:.5px'>"
            f"{cat}</span>"
            f"<div style='flex:1;height:1px;background:#e2e8f0'></div></div>"
        )
        for a in items:
            img_html = ""
            if not for_pdf:
                img_url = a.get("image_url") or ""
                if img_url and img_url.startswith(("https://", "http://")):
                    img_html = (
                        f"<img src='{img_url}' style='width:100%;max-height:140px;"
                        f"object-fit:cover;display:block' alt=''>"
                    )
            impact = a.get("impact", "HIGH")
            impact_bg = "#dc2626" if impact == "HIGH" else "#f59e0b"
            prods_html = ""
            for p in (a.get("products") or [])[:2]:
                p_img = ""
                if not for_pdf:
                    p_url = p.get("image_url") or ""
                    if p_url and p_url.startswith(("https://", "http://")):
                        p_img = (
                            f"<img src='{p_url}' style='width:24px;height:24px;"
                            f"border-radius:4px;object-fit:cover' alt=''>"
                        )
                brand = p.get("brand_name") or ""
                brand_html = (
                    f"<div style='font-size:10px;color:#94a3b8'>{brand}</div>"
                    if brand else ""
                )
                prods_html += (
                    f"<div style='display:inline-flex;align-items:center;gap:6px;"
                    f"background:#f8fafc;padding:4px 8px;border-radius:6px;"
                    f"border:1px solid #e2e8f0;margin-right:8px;margin-bottom:8px'>"
                    f"{p_img}<div style='line-height:1.2'>"
                    f"<div style='font-size:11px;font-weight:500;color:#334155'>"
                    f"{p['name']}</div>{brand_html}</div></div>"
                )
            if prods_html:
                prods_html = f"<div style='margin-bottom:12px'>{prods_html}</div>"
            market = a.get("market", "")
            market_bg = _CAT_COLORS.get(cat, "#eff6ff")
            articles_html += (
                f"<div style='background:#fff;border-radius:10px;border:1px solid #e2e8f0;"
                f"overflow:hidden;border-left:3px solid {cat_color};margin-bottom:14px'>"
                f"{img_html}"
                f"<div style='padding:16px 20px 20px'>"
                f"<div style='display:flex;justify-content:space-between;align-items:flex-start;"
                f"gap:10px;margin-bottom:10px'>"
                f"<div style='font-size:15px;font-weight:600;line-height:1.4;color:#0f172a;"
                f"flex:1'>{a['headline']}</div>"
                f"<span style='flex-shrink:0;background:{impact_bg};color:#fff;padding:2px 7px;"
                f"border-radius:4px;font-size:10px;font-weight:700'>{impact}</span></div>"
                f"<div style='font-size:13px;line-height:1.55;color:#64748b;margin-bottom:12px'>"
                f"{a.get('why_it_matters', '')}</div>"
                f"{prods_html}"
                f"<span style='display:inline-block;background:#eff6ff;color:{cat_color};"
                f"padding:2px 8px;border-radius:10px;font-size:11px;font-weight:500'>"
                f"{market}</span>"
                f"</div></div>"
            )

    trends_html = ""
    trend_icons = ["&#10024;", "&#129302;", "&#127793;", "&#128138;"]
    for i, t in enumerate(digest.get("emerging_trends") or []):
        icon = trend_icons[i % 4]
        trends_html += (
            f"<div style='background:rgba(255,255,255,0.05);border:1px solid "
            f"rgba(255,255,255,0.08);border-radius:8px;padding:16px;margin-bottom:12px'>"
            f"<div style='font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:6px'>"
            f"{icon} {t}</div></div>"
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>NewsPulse Weekly Beauty Intel Digest - {week}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=Inter:wght@400;500;600;700&display=swap');
body {{ margin:0; font-family:'Inter',system-ui,sans-serif; color:#1e293b; }}
@page {{ size: A4; margin: 0; }}
</style></head><body>

<div style="width:100%;background:#f8fafc">
  <!-- HERO -->
  <div style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 60%,#2d2240 100%);
    padding:48px 40px 44px">
    <div style="max-width:600px;margin:0 auto">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:24px">
        <div style="width:32px;height:32px;border-radius:6px;background:#d63384;
          text-align:center;line-height:32px;color:#fff;font-size:16px">&#9670;</div>
        <span style="font-weight:700;font-size:15px;color:#fff;letter-spacing:.8px">
          NEWSPULSE</span>
      </div>
      <div style="font-family:'DM Serif Display',Georgia,serif;font-size:44px;
        font-weight:400;color:#fff;line-height:1.1;margin-bottom:20px">
        Weekly Beauty<br>Intelligence Digest</div>
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <span style="background:rgba(214,51,132,0.15);color:#f9a8d4;padding:5px 12px;
          border-radius:16px;font-size:12px;font-weight:500">{week}</span>
        <span style="color:#64748b;font-size:12px">{today}</span>
      </div>
    </div>
  </div>

  <!-- EXECUTIVE SUMMARY -->
  <div style="max-width:600px;margin:0 auto;padding:40px 40px 32px">
    <div style="border-left:3px solid #d63384;padding-left:10px;font-size:11px;
      font-weight:700;text-transform:uppercase;letter-spacing:1.8px;color:#94a3b8;
      margin-bottom:16px">Executive Summary</div>
    <div style="font-family:'DM Serif Display',Georgia,serif;font-size:18px;line-height:1.7;
      color:#334155;font-style:italic">{summary}</div>
  </div>

  <!-- KEY TAKEAWAYS -->
  <div style="max-width:600px;margin:0 auto;padding:0 40px 32px">
    <div style="border-left:3px solid #d63384;padding-left:10px;font-size:11px;
      font-weight:700;text-transform:uppercase;letter-spacing:1.8px;color:#94a3b8;
      margin-bottom:20px">Key Takeaways</div>
    {takeaways_html}
  </div>

  <!-- ARTICLES -->
  <div style="max-width:600px;margin:0 auto;padding:0 40px 20px">
    <div style="border-left:3px solid #d63384;padding-left:10px;font-size:11px;
      font-weight:700;text-transform:uppercase;letter-spacing:1.8px;color:#94a3b8;
      margin-bottom:8px">This Week's Intelligence</div>
    {articles_html}
  </div>

  <!-- EMERGING TRENDS -->
  <div style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 60%,#2d2240 100%);
    padding:40px;margin-top:8px">
    <div style="max-width:600px;margin:0 auto">
      <div style="border-left:3px solid #d63384;padding-left:10px;font-size:11px;
        font-weight:700;text-transform:uppercase;letter-spacing:1.8px;color:#94a3b8;
        margin-bottom:20px">Emerging Trends</div>
      {trends_html}
    </div>
  </div>

  <!-- FOOTER -->
  <div style="padding:28px 40px;border-top:1px solid #e2e8f0;background:#fff">
    <div style="max-width:600px;margin:0 auto;display:flex;justify-content:space-between;
      align-items:center;flex-wrap:wrap;gap:12px">
      <div style="display:flex;align-items:center;gap:8px">
        <div style="width:22px;height:22px;border-radius:5px;background:#d63384;
          text-align:center;line-height:22px;color:#fff;font-size:12px">&#9670;</div>
        <span style="font-weight:700;font-size:13px;color:#334155">NewsPulse</span>
        <span style="color:#cbd5e1;font-size:13px">by AsiaCosmePulse</span>
      </div>
      <div style="font-size:12px;color:#94a3b8">
        AI-curated beauty industry intelligence</div>
    </div>
  </div>
</div>
</body></html>"""


def _generate_pdf(html: str) -> bytes:
    """Render HTML to PDF using Playwright (Chromium), with image compression."""
    import os

    from playwright.sync_api import sync_playwright

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(html.encode())
        html_path = f.name

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 680, "height": 960})
        page.goto(f"file://{html_path}", wait_until="load")
        pdf_bytes = page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            scale=0.95,
        )
        browser.close()

    os.unlink(html_path)
    return pdf_bytes


def generate_digest() -> dict:
    start = time.time()
    results: dict = {}
    headline_extras: dict = {}
    week = _week_label()
    print(f"[digest] Generating weekly digest for {week}", flush=True)

    print("[digest] Step 1/4: Fetching top articles...", flush=True)
    try:
        engine = create_engine(settings.publish_database_url, pool_pre_ping=True)
        articles = _fetch_top_articles(engine)
        article_ids = [a["id"] for a in articles]
        products_map = _fetch_related_products(engine, article_ids)
        engine.dispose()
        for a in articles:
            headline_extras[a["headline"]] = {
                "image_url": a.get("image_url"),
                "url": a.get("url"),
                "products": products_map.get(a["id"], []),
            }
        results["articles_fetched"] = len(articles)
        print(f"[digest] Found {len(articles)} articles", flush=True)
    except Exception as e:
        print(f"[digest] FATAL: DB query failed: {e}", flush=True)
        results["error"] = str(e)
        return results

    if not articles:
        print("[digest] No qualifying articles -- skipping generation", flush=True)
        results["skipped"] = "no articles"
        return results

    print("[digest] Step 2/4: Generating report via Mistral...", flush=True)
    try:
        user_prompt = (
            f"Week: {week}\n\n"
            f"Articles ({len(articles)}):\n"
            + json.dumps(articles, indent=2, default=str)
        )
        client = httpx.Client(timeout=120.0)
        content, usage = chat_json(
            client, settings.mistral_api_key, settings.mistral_model,
            SYSTEM_PROMPT, user_prompt,
        )
        client.close()
        digest = json.loads(content)
        digest["week"] = week
        for cat_items in (digest.get("categories") or {}).values():
            for item in cat_items:
                extras = headline_extras.get(item.get("headline"), {})
                if extras:
                    item.setdefault("image_url", extras.get("image_url"))
                    item.setdefault("url", extras.get("url"))
                    item.setdefault("products", extras.get("products", []))
        results["usage"] = usage
        print(f"[digest] Report generated (tokens: {usage})", flush=True)
    except Exception as e:
        print(f"[digest] FATAL: Mistral generation failed: {e}", flush=True)
        results["generation_error"] = str(e)
        return results

    print("[digest] Step 3/4: Saving JSON + HTML to storage...", flush=True)
    try:
        storage = get_storage()
        json_key = f"digests/{week}_weekly-digest.json"
        html_key = f"digests/{week}_weekly-digest.html"
        storage.put(json_key, json.dumps(digest, indent=2, default=str).encode())
        storage.put(html_key, _render_html(digest).encode())
        results["json_key"] = json_key
        results["html_key"] = html_key
        print(f"[digest] Saved: {json_key}, {html_key}", flush=True)
    except Exception as e:
        print(f"[digest] ERROR: Storage save failed: {e}", flush=True)
        results["storage_error"] = str(e)

    print("[digest] Step 4/4: Generating premium PDF...", flush=True)
    try:
        premium_html = _render_premium_html(digest, for_pdf=True)
        pdf_bytes = _generate_pdf(premium_html)
        today_str = date.today().isoformat()
        pdf_key = f"digests/NewsPulse_Weekly_Digest_{week}_{today_str}.pdf"
        storage.put(pdf_key, pdf_bytes)
        results["pdf_key"] = pdf_key
        results["pdf_size_kb"] = round(len(pdf_bytes) / 1024, 1)
        print(f"[digest] PDF saved: {pdf_key} ({results['pdf_size_kb']} KB)", flush=True)
    except Exception as e:
        print(f"[digest] ERROR: PDF generation failed: {e}", flush=True)
        results["pdf_error"] = str(e)

    elapsed = round(time.time() - start, 1)
    results["elapsed_seconds"] = elapsed
    print(f"[digest] Complete in {elapsed}s", flush=True)
    return results


def main() -> None:
    result = generate_digest()
    errors = [k for k in result if k.endswith("_error")]
    if errors:
        print(f"\n[digest] FINISHED WITH ERRORS: {errors}")
        print(f"[digest] Result: {result}")
        sys.exit(1)
    print(f"\n[digest] SUCCESS: {result}")


if __name__ == "__main__":
    main()
