"""Part 8.3 — clustering functions + embed/cluster pipeline (offline)."""

from newspulse.models import ArticleReport, RawItem, Source
from newspulse.reports.cluster import cosine, greedy_cluster
from newspulse.reports.embedder import FakeEmbedder
from newspulse.reports.pipeline import build_clusters, embed_pending


# --- pure functions -----------------------------------------------------
def test_cosine() -> None:
    assert cosine([1, 0], [1, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([1, 0], [0, 0]) == 0.0  # zero vector safe


def test_greedy_cluster_groups_similar() -> None:
    items = [(1, [1.0, 0.0]), (2, [0.98, 0.2]), (3, [0.0, 1.0])]
    groups = greedy_cluster(items, threshold=0.9)
    assert groups == [[1, 2], [3]]  # 1&2 similar, 3 apart


# --- pipeline -----------------------------------------------------------
def _report(session, *, hash_, summary, related=True) -> ArticleReport:
    src = session.query(Source).filter_by(name="Src").one_or_none()
    if src is None:
        src = Source(name="Src", url="https://e", type="news")
        session.add(src)
        session.flush()
    ri = RawItem(source_id=src.id, url=f"https://e/{hash_}", content_hash=hash_)
    session.add(ri)
    session.flush()
    rep = ArticleReport(
        raw_item_id=ri.id, is_product_related=related, title=summary, summary=summary
    )
    session.add(rep)
    session.flush()
    return rep


def test_embed_pending_sets_vectors(db_session) -> None:
    _report(db_session, hash_="a", summary="body wash for dry skin")
    _report(db_session, hash_="b", summary="celebrity news", related=False)
    embedder = FakeEmbedder({"body wash for dry skin": [1.0, 0.0]})
    stats = embed_pending(embedder, session=db_session)
    assert stats["embedded"] == 1  # only the product-related one
    rep = db_session.query(ArticleReport).filter_by(summary="body wash for dry skin").one()
    assert rep.embedding == [1.0, 0.0]


def test_build_clusters_groups_and_assigns(db_session) -> None:
    a = _report(db_session, hash_="a", summary="salicylic acid body wash")
    b = _report(db_session, hash_="b", summary="salicylic acid cleanser")
    c = _report(db_session, hash_="c", summary="rose perfume launch")
    a.embedding, b.embedding, c.embedding = [1.0, 0.0], [0.97, 0.24], [0.0, 1.0]
    db_session.flush()

    stats = build_clusters(session=db_session, threshold=0.9)
    assert stats == {"reports": 3, "clusters": 2}
    db_session.refresh(a)
    db_session.refresh(b)
    db_session.refresh(c)
    assert a.cluster_id == b.cluster_id  # merged
    assert c.cluster_id != a.cluster_id  # separate
