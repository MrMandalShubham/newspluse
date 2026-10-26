"""Catalog matcher — link news-extracted names to existing catalog rows.

News mentions casual names ("Snail 96 Mucin Essence"); the retail catalog stores
full SKU titles. Exact matching misses most of them and creates duplicate
news-only rows instead of linking to real Olive Young / @cosme products. This
matcher loads the catalog once and resolves a name via, in order:

  1. exact normalized match (lowercased, punctuation/size tokens stripped),
  2. brand alias (English/Korean/typo variants -> canonical),
  3. fuzzy match (rapidfuzz), for products scoped to the article's brands so the
     candidate set is small and precise.

Thresholds are deliberately conservative: linking the WRONG retail SKU is worse
than creating a news-only row, so a weak fuzzy hit falls through to "no match".
"""

import re

from rapidfuzz import fuzz, process

_MATCHER_ALLOWED_TABLES = frozenset({"companies", "ingredients"})

# Brand-name variants -> canonical catalog spelling (extend as needed).
BRAND_ALIASES = {
    "beauty of josen": "beauty of joseon",
    "beautyofjoseon": "beauty of joseon",
    "beauty of joson": "beauty of joseon",
    "medi cube": "medicube",
    "medi-cube": "medicube",
    "cos rx": "cosrx",
    "laniege": "laneige",
    "sulwha soo": "sulwhasoo",
    "amore pacific": "amorepacific",
    "innis free": "innisfree",
    "round lab": "round lab",
    "tir tir": "tirtir",
    "anua beauty": "anua",
}

# Fuzzy score thresholds (0-100). Higher = stricter.
BRAND_FUZZY = 90
PRODUCT_IN_BRAND_FUZZY = 84  # within the article's brands -> small, trusted set
PRODUCT_GLOBAL_FUZZY = 93    # across all products -> must be near-identical
LOOKUP_FUZZY = 92            # companies / ingredients

_SIZE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:ml|g|kg|l|oz|fl\.?oz|pcs|pack|packs|set|sets|ea|x\d+)\b",
    re.IGNORECASE,
)
_TM_RE = re.compile(r"[™®©]")


def normalize(name: str | None) -> str:
    """Lowercase; drop trademark marks, size/volume tokens, and punctuation."""
    if not name:
        return ""
    s = _TM_RE.sub(" ", name.lower())
    s = _SIZE_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9가-힣]+", " ", s)  # keep ascii alnum + Hangul
    return re.sub(r"\s+", " ", s).strip()


def _alias(norm: str) -> str:
    return BRAND_ALIASES.get(norm, norm)


class CatalogMatcher:
    """In-memory index over the platform catalog for fast, fuzzy name resolution."""

    def __init__(self, conn) -> None:
        self._conn = conn
        # brand: normalized-name -> id ; and a list of (norm, id) for fuzzy
        self._brand_exact: dict[str, object] = {}
        self._brand_names: list[str] = []
        self._brand_name_to_id: dict[str, object] = {}
        # products, REAL retail only (data_source != newspulse): prefer these
        self._retail_exact: dict[str, object] = {}
        self._retail_by_brand: dict[object, dict[str, object]] = {}
        self._retail_names: list[str] = []
        self._retail_ids: set[object] = set()
        # products, news-created (newspulse): exact fallback only, never fuzzy
        self._news_exact: dict[str, object] = {}
        # companies / ingredients: kind -> (exact dict, names list)
        self._lookup_exact: dict[str, dict[str, object]] = {"companies": {}, "ingredients": {}}
        self._lookup_names: dict[str, list[str]] = {"companies": [], "ingredients": []}
        self._load()

    def _load(self) -> None:
        from sqlalchemy import text

        for row in self._conn.execute(text("select id, name, name_kr from brands")):
            for nm in (row.name, row.name_kr):
                n = normalize(nm)
                if n and n not in self._brand_exact:
                    self._brand_exact[n] = row.id
                    self._brand_name_to_id[n] = row.id
                    self._brand_names.append(n)
        for row in self._conn.execute(
            text("select id, name, brand_id, data_source from products_master "
                 "where name is not null")
        ):
            n = normalize(row.name)
            if not n:
                continue
            if (row.data_source or "") == "newspulse":
                self._news_exact.setdefault(n, row.id)
            else:
                self._retail_ids.add(row.id)
                if n not in self._retail_exact:
                    self._retail_exact[n] = row.id
                    self._retail_names.append(n)
                if row.brand_id is not None:
                    self._retail_by_brand.setdefault(row.brand_id, {}).setdefault(n, row.id)
        for kind, table in (("companies", "companies"), ("ingredients", "ingredients")):
            assert table in _MATCHER_ALLOWED_TABLES, f"unexpected table: {table}"
            for row in self._conn.execute(text(f"select id, name from {table}")):
                n = normalize(row.name)
                if n:
                    self._lookup_exact[kind].setdefault(n, row.id)
                    self._lookup_names[kind].append(n)

    def is_retail(self, product_id: object) -> bool:
        return product_id in self._retail_ids

    # --- matching -------------------------------------------------------
    def match_brand(self, name: str) -> object | None:
        n = _alias(normalize(name))
        if not n:
            return None
        if n in self._brand_exact:
            return self._brand_exact[n]
        hit = process.extractOne(n, self._brand_names, scorer=fuzz.token_sort_ratio)
        if hit and hit[1] >= BRAND_FUZZY:
            return self._brand_name_to_id[hit[0]]
        return None

    def match_product(self, name: str, brand_ids: list[object]) -> object | None:
        """Resolve a product name, PREFERRING real retail SKUs over news-created rows.

        Order: retail exact -> retail fuzzy within the article's brands -> retail
        global fuzzy (near-identical) -> existing news-created row (exact) -> None.
        """
        n = normalize(name)
        if not n:
            return None
        if n in self._retail_exact:
            return self._retail_exact[n]
        for bid in brand_ids:  # scoped fuzzy: small, trusted candidate set
            candidates = self._retail_by_brand.get(bid)
            if not candidates:
                continue
            hit = process.extractOne(n, list(candidates), scorer=fuzz.token_sort_ratio)
            if hit and hit[1] >= PRODUCT_IN_BRAND_FUZZY:
                return candidates[hit[0]]
        if self._retail_names:  # global fuzzy: must be near-identical
            hit = process.extractOne(n, self._retail_names, scorer=fuzz.token_sort_ratio)
            if hit and hit[1] >= PRODUCT_GLOBAL_FUZZY:
                return self._retail_exact[hit[0]]
        return self._news_exact.get(n)  # fall back to the existing news-only row

    def match_lookup(self, kind: str, name: str) -> object | None:
        n = normalize(name)
        if not n:
            return None
        exact = self._lookup_exact[kind]
        if n in exact:
            return exact[n]
        hit = process.extractOne(n, self._lookup_names[kind], scorer=fuzz.token_sort_ratio)
        if hit and hit[1] >= LOOKUP_FUZZY:
            return exact[hit[0]]
        return None

    # --- keep the index fresh after inserts -----------------------------
    def add_brand(self, name: str, brand_id: object) -> None:
        n = _alias(normalize(name))
        if n and n not in self._brand_exact:
            self._brand_exact[n] = brand_id
            self._brand_name_to_id[n] = brand_id
            self._brand_names.append(n)

    def add_product(self, name: str, product_id: object) -> None:
        """Register a newly-created (news-only) product so later names reuse it."""
        n = normalize(name)
        if n:
            self._news_exact.setdefault(n, product_id)

    def add_lookup(self, kind: str, name: str, entity_id: object) -> None:
        n = normalize(name)
        if n and n not in self._lookup_exact[kind]:
            self._lookup_exact[kind][n] = entity_id
            self._lookup_names[kind].append(n)
