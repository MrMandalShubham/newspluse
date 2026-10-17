"""Seed 20 themes into the platform DB.

    python -m newspulse.publish.seed_themes

Idempotent: skips themes whose slug already exists.
"""

import uuid

from sqlalchemy import create_engine, text

from newspulse.config import settings
from newspulse.db import Base

THEMES = [
    {
        "slug": "clean-beauty",
        "label_en": "Clean Beauty",
        "label_fr": "Beaute Propre",
        "label_kr": "클린 뷰티",
        "label_jp": "クリーンビューティー",
        "label_zh": "清洁美容",
        "description": (
            "Products free from controversial ingredients,"
            " emphasizing transparency and safety."
        ),
        "type": "macro-trend",
        "lifecycle": "growth",
        "facet_geography": ["US", "KR", "GB"],
        "facet_category": ["skincare", "haircare", "cosmetics"],
        "facet_need": ["safety", "transparency"],
        "facet_values": ["clean", "non-toxic"],
    },
    {
        "slug": "k-beauty-innovation",
        "label_en": "K-Beauty Innovation",
        "label_kr": "케이뷰티 혁신",
        "label_jp": "Kビューティーイノベーション",
        "description": "South Korean beauty trends driving global product innovation.",
        "type": "macro-trend",
        "lifecycle": "mature",
        "facet_geography": ["KR"],
        "facet_category": ["skincare", "cosmetics"],
        "facet_channel": ["online", "duty-free"],
    },
    {
        "slug": "j-beauty-minimalism",
        "label_en": "J-Beauty Minimalism",
        "label_jp": "Jビューティーミニマリズム",
        "description": "Japanese approach to beauty emphasizing fewer, high-quality products.",
        "type": "macro-trend",
        "lifecycle": "mature",
        "facet_geography": ["JP"],
        "facet_category": ["skincare"],
        "facet_values": ["minimalism", "quality"],
    },
    {
        "slug": "glass-skin",
        "label_en": "Glass Skin",
        "label_kr": "유리 피부",
        "description": "Dewy, translucent skin trend originating from Korean beauty culture.",
        "type": "micro-trend",
        "lifecycle": "growth",
        "facet_geography": ["KR", "US", "CN"],
        "facet_category": ["skincare"],
        "facet_need": ["hydration", "glow"],
    },
    {
        "slug": "retinol",
        "label_en": "Retinol",
        "label_fr": "Retinol",
        "label_kr": "레티놀",
        "label_jp": "レチノール",
        "label_zh": "视黄醇",
        "description": (
            "Vitamin A derivative used for anti-aging,"
            " acne treatment, and skin renewal."
        ),
        "type": "ingredient",
        "lifecycle": "mature",
        "facet_category": ["skincare"],
        "facet_need": ["anti-aging", "acne"],
    },
    {
        "slug": "niacinamide",
        "label_en": "Niacinamide",
        "label_kr": "나이아신아마이드",
        "label_jp": "ナイアシンアミド",
        "label_zh": "烟酰胺",
        "description": (
            "Vitamin B3 derivative for brightening,"
            " pore refinement, and barrier repair."
        ),
        "type": "ingredient",
        "lifecycle": "growth",
        "facet_category": ["skincare"],
        "facet_need": ["brightening", "pore-care", "barrier-repair"],
    },
    {
        "slug": "hyaluronic-acid",
        "label_en": "Hyaluronic Acid",
        "label_kr": "히알루론산",
        "label_jp": "ヒアルロン酸",
        "label_zh": "透明质酸",
        "description": "Humectant that attracts moisture; used across skincare for hydration.",
        "type": "ingredient",
        "lifecycle": "mature",
        "facet_category": ["skincare"],
        "facet_need": ["hydration"],
    },
    {
        "slug": "cica-centella",
        "label_en": "Cica / Centella Asiatica",
        "label_kr": "시카",
        "label_jp": "シカ",
        "label_zh": "积雪草",
        "description": "Soothing botanical extract for sensitive and irritated skin.",
        "type": "ingredient",
        "lifecycle": "growth",
        "facet_geography": ["KR", "JP"],
        "facet_category": ["skincare"],
        "facet_need": ["soothing", "repair"],
    },
    {
        "slug": "peptides",
        "label_en": "Peptides",
        "label_kr": "펩타이드",
        "label_jp": "ペプチド",
        "label_zh": "肽",
        "description": "Short amino acid chains that signal collagen production for anti-aging.",
        "type": "ingredient",
        "lifecycle": "growth",
        "facet_category": ["skincare"],
        "facet_need": ["anti-aging", "firming"],
    },
    {
        "slug": "vegan-beauty",
        "label_en": "Vegan Beauty",
        "label_fr": "Beaute Vegane",
        "label_kr": "비건 뷰티",
        "description": "Products free from animal-derived ingredients and not tested on animals.",
        "type": "claim",
        "lifecycle": "growth",
        "facet_geography": ["GB", "US", "KR"],
        "facet_category": ["skincare", "cosmetics", "haircare"],
        "facet_values": ["vegan", "cruelty-free"],
    },
    {
        "slug": "dermocosmetics",
        "label_en": "Dermocosmetics",
        "label_fr": "Dermocosmetiques",
        "label_kr": "더모코스메틱",
        "description": "Clinically validated skincare bridging cosmetics and dermatology.",
        "type": "claim",
        "lifecycle": "growth",
        "facet_geography": ["KR", "JP", "US"],
        "facet_category": ["skincare"],
        "facet_need": ["efficacy", "clinical-proof"],
    },
    {
        "slug": "sustainable-packaging",
        "label_en": "Sustainable Packaging",
        "label_fr": "Emballage Durable",
        "label_kr": "지속가능한 패키징",
        "label_zh": "可持续包装",
        "description": "Refillable, recyclable, and reduced-plastic packaging in beauty.",
        "type": "sustainability",
        "lifecycle": "growth",
        "facet_geography": ["GB", "US", "JP"],
        "facet_category": ["skincare", "cosmetics"],
        "facet_values": ["eco-friendly", "refillable"],
    },
    {
        "slug": "gen-z-beauty",
        "label_en": "Gen-Z Beauty",
        "label_kr": "Z세대 뷰티",
        "description": "Beauty preferences and purchasing behaviour of consumers born 1997-2012.",
        "type": "segment",
        "lifecycle": "growth",
        "facet_geography": ["US", "KR", "CN"],
        "facet_channel": ["social-commerce", "online"],
    },
    {
        "slug": "mens-grooming",
        "label_en": "Men's Grooming",
        "label_kr": "남성 그루밍",
        "label_jp": "メンズグルーミング",
        "label_zh": "男士护理",
        "description": (
            "Growing market for skincare, haircare,"
            " and cosmetics targeting male consumers."
        ),
        "type": "segment",
        "lifecycle": "growth",
        "facet_geography": ["KR", "CN", "IN"],
        "facet_category": ["skincare", "haircare"],
    },
    {
        "slug": "spf-protection",
        "label_en": "SPF / Sun Protection",
        "label_kr": "자외선 차단",
        "label_jp": "日焼け止め",
        "label_zh": "防晒",
        "description": "Sunscreen and UV protection products, a staple in Asian beauty routines.",
        "type": "need",
        "lifecycle": "mature",
        "facet_geography": ["KR", "JP", "US"],
        "facet_category": ["skincare"],
        "facet_need": ["sun-protection"],
    },
    {
        "slug": "anti-aging",
        "label_en": "Anti-Aging",
        "label_fr": "Anti-Age",
        "label_kr": "안티에이징",
        "label_jp": "アンチエイジング",
        "label_zh": "抗衰老",
        "description": (
            "Products and ingredients targeting signs"
            " of aging: wrinkles, firmness, spots."
        ),
        "type": "need",
        "lifecycle": "mature",
        "facet_category": ["skincare"],
        "facet_need": ["anti-aging", "firming", "brightening"],
    },
    {
        "slug": "social-commerce",
        "label_en": "Social Commerce",
        "label_kr": "소셜커머스",
        "label_zh": "社交电商",
        "description": "Purchasing beauty products directly through social media platforms.",
        "type": "channel",
        "lifecycle": "growth",
        "facet_geography": ["CN", "US", "KR"],
        "facet_channel": ["tiktok-shop", "instagram", "live-commerce"],
    },
    {
        "slug": "eu-cosmetics-regulation",
        "label_en": "EU Cosmetics Regulation",
        "label_fr": "Reglementation Cosmetiques UE",
        "description": "EU regulatory framework (EC 1223/2009) governing cosmetic product safety.",
        "type": "regulatory",
        "lifecycle": "mature",
        "facet_geography": ["GB"],
        "facet_category": ["skincare", "cosmetics", "haircare"],
    },
    {
        "slug": "scalp-care",
        "label_en": "Scalp Care",
        "label_kr": "두피 케어",
        "label_jp": "スカルプケア",
        "description": (
            "Targeted treatments for scalp health:"
            " exfoliation, microbiome balance, DHT blocking."
        ),
        "type": "micro-trend",
        "lifecycle": "emerging",
        "facet_geography": ["KR", "JP"],
        "facet_category": ["haircare"],
        "facet_need": ["scalp-health"],
    },
    {
        "slug": "waterless-beauty",
        "label_en": "Waterless Beauty",
        "label_kr": "워터리스 뷰티",
        "description": "Concentrated, anhydrous formulations that reduce water usage.",
        "type": "sustainability",
        "lifecycle": "emerging",
        "facet_geography": ["KR", "US"],
        "facet_category": ["skincare", "haircare"],
        "facet_values": ["eco-friendly", "concentrated"],
    },
]

ALIASES = [
    ("clean-beauty", "Clean Label Beauty", "en", "synonym"),
    ("clean-beauty", "Non-Toxic Beauty", "en", "synonym"),
    ("retinol", "Vitamin A", "en", "synonym"),
    ("retinol", "Retin-A", "en", "abbreviation"),
    ("niacinamide", "Vitamin B3", "en", "synonym"),
    ("niacinamide", "Nicotinamide", "en", "synonym"),
    ("hyaluronic-acid", "HA", "en", "abbreviation"),
    ("cica-centella", "Centella", "en", "synonym"),
    ("cica-centella", "Tiger Grass", "en", "synonym"),
    ("cica-centella", "병풀", "kr", "translation"),
    ("glass-skin", "Chok-Chok Skin", "en", "synonym"),
    ("vegan-beauty", "Cruelty-Free Beauty", "en", "synonym"),
    ("spf-protection", "Sunscreen", "en", "synonym"),
    ("anti-aging", "Pro-Aging", "en", "synonym"),
    ("social-commerce", "Live Commerce", "en", "synonym"),
]

RELATIONS = [
    ("retinol", "anti-aging", "contributes-to", 0.9),
    ("niacinamide", "glass-skin", "contributes-to", 0.7),
    ("hyaluronic-acid", "glass-skin", "contributes-to", 0.8),
    ("cica-centella", "k-beauty-innovation", "belongs-to", 0.8),
    ("peptides", "anti-aging", "contributes-to", 0.85),
    ("clean-beauty", "vegan-beauty", "overlaps", 0.6),
    ("clean-beauty", "sustainable-packaging", "overlaps", 0.5),
    ("glass-skin", "k-beauty-innovation", "belongs-to", 0.7),
    ("gen-z-beauty", "social-commerce", "drives", 0.75),
    ("scalp-care", "k-beauty-innovation", "belongs-to", 0.5),
    ("dermocosmetics", "retinol", "uses", 0.6),
    ("waterless-beauty", "sustainable-packaging", "overlaps", 0.7),
]


def _json(val):
    """Return JSON-castable string or None."""
    if val is None:
        return None
    import json
    return json.dumps(val)


def seed_themes() -> dict:
    from newspulse.publish.platform import NEW_TABLES

    plat = create_engine(settings.publish_database_url)
    Base.metadata.create_all(plat, tables=NEW_TABLES, checkfirst=True)

    stats = {"themes": 0, "aliases": 0, "relations": 0, "skipped": 0}
    slug_to_id: dict[str, uuid.UUID] = {}

    with plat.begin() as conn:
        for facet in ("geography", "category", "need", "ingredient", "values", "channel"):
            conn.execute(
                text(f"CREATE INDEX IF NOT EXISTS ix_themes_facet_{facet} "
                     f"ON themes USING gin(facet_{facet} jsonb_path_ops)")
            )

        for t in THEMES:
            row = conn.execute(
                text("SELECT id FROM themes WHERE slug = :s"), {"s": t["slug"]}
            ).first()
            if row:
                slug_to_id[t["slug"]] = row[0]
                stats["skipped"] += 1
                continue
            tid = uuid.uuid4()
            slug_to_id[t["slug"]] = tid

            ingredient_id = None
            if t["type"] == "ingredient":
                ing = conn.execute(
                    text("SELECT id FROM ingredients WHERE lower(name) = lower(:n)"),
                    {"n": t["label_en"]},
                ).first()
                if ing:
                    ingredient_id = ing[0]

            conn.execute(
                text(
                    "INSERT INTO themes(id, slug, label_en, label_fr, label_kr, label_jp, "
                    "label_zh, description, type, facet_geography, facet_category, "
                    "facet_need, facet_ingredient, facet_values, facet_channel, "
                    "ingredient_id, lifecycle, status, created_at, updated_at) "
                    "VALUES(:id, :slug, :label_en, :label_fr, :label_kr, :label_jp, "
                    ":label_zh, :description, :type, "
                    "cast(:fg as jsonb), cast(:fc as jsonb), cast(:fn as jsonb), "
                    "cast(:fi as jsonb), cast(:fv as jsonb), cast(:fch as jsonb), "
                    ":ingredient_id, :lifecycle, 'active', now(), now())"
                ),
                {
                    "id": tid,
                    "slug": t["slug"],
                    "label_en": t["label_en"],
                    "label_fr": t.get("label_fr"),
                    "label_kr": t.get("label_kr"),
                    "label_jp": t.get("label_jp"),
                    "label_zh": t.get("label_zh"),
                    "description": t.get("description"),
                    "type": t["type"],
                    "fg": _json(t.get("facet_geography")),
                    "fc": _json(t.get("facet_category")),
                    "fn": _json(t.get("facet_need")),
                    "fi": _json(t.get("facet_ingredient")),
                    "fv": _json(t.get("facet_values")),
                    "fch": _json(t.get("facet_channel")),
                    "ingredient_id": ingredient_id,
                    "lifecycle": t.get("lifecycle"),
                },
            )
            stats["themes"] += 1

        for slug, alias_text, lang, atype in ALIASES:
            theme_id = slug_to_id.get(slug)
            if not theme_id:
                continue
            exists = conn.execute(
                text("SELECT 1 FROM theme_aliases WHERE theme_id = :tid AND alias = :a"),
                {"tid": theme_id, "a": alias_text},
            ).first()
            if exists:
                continue
            conn.execute(
                text(
                    "INSERT INTO theme_aliases(id, theme_id, alias, language, alias_type) "
                    "VALUES(:id, :tid, :a, :l, :at)"
                ),
                {"id": uuid.uuid4(), "tid": theme_id, "a": alias_text, "l": lang, "at": atype},
            )
            stats["aliases"] += 1

        for src_slug, tgt_slug, rel_type, strength in RELATIONS:
            src_id = slug_to_id.get(src_slug)
            tgt_id = slug_to_id.get(tgt_slug)
            if not src_id or not tgt_id:
                continue
            exists = conn.execute(
                text(
                    "SELECT 1 FROM theme_relations "
                    "WHERE source_theme_id = :s AND target_theme_id = :t AND relation_type = :r"
                ),
                {"s": src_id, "t": tgt_id, "r": rel_type},
            ).first()
            if exists:
                continue
            conn.execute(
                text(
                    "INSERT INTO theme_relations(id, source_theme_id, target_theme_id, "
                    "relation_type, strength) VALUES(:id, :s, :t, :r, :str)"
                ),
                {"id": uuid.uuid4(), "s": src_id, "t": tgt_id, "r": rel_type, "str": strength},
            )
            stats["relations"] += 1

    plat.dispose()
    return stats


def main() -> None:
    result = seed_themes()
    print(f"[seed_themes] {result}")


if __name__ == "__main__":
    main()
