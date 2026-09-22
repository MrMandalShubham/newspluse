"""Catalog matcher — normalization, alias, retail-preference, fuzzy (offline)."""

import uuid

from newspulse.publish.matcher import CatalogMatcher, normalize


def test_normalize_strips_size_and_punctuation() -> None:
    assert normalize("Advanced Snail 96 Mucin Power Essence 100ml") == (
        "advanced snail 96 mucin power essence"
    )
    assert normalize("COSRX®") == "cosrx"
    assert normalize(None) == ""


class _FakeConn:
    """Minimal stand-in returning preset rows per query substring."""

    def __init__(self, brands, products, companies, ingredients):
        self._data = {
            "from brands": brands,
            "products_master": products,
            "from companies": companies,
            "from ingredients": ingredients,
        }

    def execute(self, clause):
        sql = str(clause)
        for key, rows in self._data.items():
            if key in sql:
                return rows
        return []


def _row(**kw):
    return type("R", (), kw)()


def _matcher():
    rid, nid = uuid.uuid4(), uuid.uuid4()
    bid = uuid.uuid4()
    brands = [_row(id=bid, name="Beauty of Joseon", name_kr="조선미녀")]
    products = [
        _row(id=rid, name="Relief Sun Rice Probiotics SPF50", brand_id=bid,
             data_source="Olive Young Global"),
        _row(id=nid, name="Some Random News Product", brand_id=None, data_source="newspulse"),
    ]
    m = CatalogMatcher(_FakeConn(brands, products, [], []))
    return m, bid, rid, nid


def test_brand_alias_and_fuzzy() -> None:
    m, bid, _, _ = _matcher()
    assert m.match_brand("Beauty of Josen") == bid   # alias/typo
    assert m.match_brand("beauty of joseon") == bid   # exact-normalized
    assert m.match_brand("Totally Different Brand") is None


def test_product_prefers_retail_and_scopes_by_brand() -> None:
    m, bid, rid, nid = _matcher()
    # near-name within the article's brand -> real retail SKU
    assert m.match_product("Relief Sun Rice Probiotics", [bid]) == rid
    assert m.is_retail(rid) is True
    # a news-only name falls back to the existing news row (not fuzzy-forced)
    assert m.match_product("Some Random News Product", [bid]) == nid
    assert m.match_product("Nothing Like Anything Here", []) is None
