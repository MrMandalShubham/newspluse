"""Part 2.1 — entity normalization and get-or-create."""

from newspulse.enrich.entities import EntityResolver, normalize_name
from newspulse.models import Entity


def test_normalize_name() -> None:
    assert normalize_name("  Vitamin  B3 ") == "vitamin b3"
    assert normalize_name("Hyaluronic-Acid") == "hyaluronic acid"


def test_hyphenated_forms_merge(db_session) -> None:
    r = EntityResolver(db_session)
    a = r.resolve("hyaluronic-acid", "ingredient")
    b = r.resolve("Hyaluronic Acid", "ingredient")
    assert a.id == b.id
    # 'botulinum-toxin' -> normalizes to seed alias 'botulinum toxin' -> canonical 'botox'
    c = r.resolve("botulinum-toxin")
    assert c.canonical_name == "botox"
    assert db_session.query(Entity).count() == 2  # hyaluronic acid + botox


def test_aliases_resolve_to_one_canonical(db_session) -> None:
    r = EntityResolver(db_session)
    a = r.resolve("Vitamin B3")
    b = r.resolve("niacinamide")
    c = r.resolve("Nicotinamide")
    assert a.id == b.id == c.id
    assert a.canonical_name == "niacinamide"
    assert a.type == "ingredient"
    assert db_session.query(Entity).count() == 1


def test_get_or_create_is_idempotent_across_resolvers(db_session) -> None:
    EntityResolver(db_session).resolve("Retinol")
    EntityResolver(db_session).resolve("retinoid")  # seed alias of retinol
    assert db_session.query(Entity).count() == 1


def test_unknown_name_uses_given_type(db_session) -> None:
    e = EntityResolver(db_session).resolve("The Ordinary", "brand")
    assert e.type == "brand"
    assert e.canonical_name == "The Ordinary"
    # case-insensitive dedup for non-seed names too
    again = EntityResolver(db_session).resolve("the ordinary", "brand")
    assert again.id == e.id
    assert db_session.query(Entity).count() == 1
