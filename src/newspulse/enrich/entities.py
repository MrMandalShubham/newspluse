"""Entity normalization — map many surface forms to one canonical entity.

Accurate trend counting depends on this: "Vitamin B3", "niacinamide", and
"nicotinamide" must all resolve to a single ``entities`` row. A small seed
dictionary handles well-known beauty ingredients; anything else is created
on first sight (get-or-create), case-insensitively.

Provider-agnostic — no LLM involved here.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newspulse.models import Entity


def normalize_name(name: str) -> str:
    """Lowercase, trim, treat hyphens/underscores as spaces, collapse whitespace.

    Folding hyphens keeps variants like "hyaluronic-acid" and "hyaluronic acid"
    (or "botulinum-toxin" -> seed alias "botulinum toxin") on one entity.
    """
    cleaned = name.strip().lower().replace("-", " ").replace("_", " ")
    return " ".join(cleaned.split())


# canonical display name -> (entity type, alias surface forms)
ALIAS_SEED: dict[str, tuple[str, list[str]]] = {
    "niacinamide": ("ingredient", ["vitamin b3", "nicotinamide"]),
    "hyaluronic acid": ("ingredient", ["ha", "sodium hyaluronate"]),
    "salicylic acid": ("ingredient", ["bha"]),
    "glycolic acid": ("ingredient", ["aha"]),
    "retinol": ("ingredient", ["retinoid", "vitamin a"]),
    "vitamin c": ("ingredient", ["ascorbic acid", "l-ascorbic acid"]),
    "glycerin": ("ingredient", ["glycerol"]),
    "ceramide": ("ingredient", ["ceramides"]),
    "peptide": ("ingredient", ["peptides"]),
    "collagen": ("ingredient", []),
    "botox": ("ingredient", ["botulinum toxin"]),
    "dermal filler": ("ingredient", ["dermal fillers", "fillers"]),
}

# normalized alias/canonical -> canonical display name
_ALIAS_INDEX: dict[str, str] = {}
for _canon, (_etype, _aliases) in ALIAS_SEED.items():
    _ALIAS_INDEX[normalize_name(_canon)] = _canon
    for _a in _aliases:
        _ALIAS_INDEX[normalize_name(_a)] = _canon


class EntityResolver:
    """Resolves surface names to canonical ``Entity`` rows (get-or-create)."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self._cache: dict[tuple[str, str], Entity] = {}

    def resolve(self, name: str, type_: str | None = None) -> Entity:
        norm = normalize_name(name)
        canon = _ALIAS_INDEX.get(norm)
        if canon is not None:
            etype, aliases = ALIAS_SEED[canon]
            display = canon
        else:
            etype = type_ or "unknown"
            aliases = []
            display = name.strip()

        key = (etype, normalize_name(display))
        if key in self._cache:
            return self._cache[key]

        entity = self.session.execute(
            select(Entity).where(
                Entity.type == etype,
                func.lower(Entity.canonical_name) == normalize_name(display),
            )
        ).scalar_one_or_none()
        if entity is None:
            entity = Entity(type=etype, canonical_name=display, aliases=aliases)
            self.session.add(entity)
            self.session.flush()

        self._cache[key] = entity
        return entity
