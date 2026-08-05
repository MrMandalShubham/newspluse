"""Part 8.4 — merge clusters, render product report, product API."""

from fastapi.testclient import TestClient

from newspulse.db import get_session
from newspulse.main import app
from newspulse.models import ArticleReport, RawItem, ReportCluster, Source
from newspulse.reports.merger import FakeMerger, MergedStory, MistralMerger
from newspulse.reports.pipeline import merge_clusters
from newspulse.reports.render import render_product_report


def _cluster_with_members(session, label, summaries, size) -> ReportCluster:
    src = session.query(Source).filter_by(name="Src").one_or_none()
    if src is None:
        src = Source(name="Src", url="https://e", type="news")
        session.add(src)
        session.flush()
    cluster = ReportCluster(label=label, summary="", size=size)
    session.add(cluster)
    session.flush()
    for i, summ in enumerate(summaries):
        ri = RawItem(source_id=src.id, url=f"https://e/{label}-{i}", title=f"{label} {i}",
                     content_hash=f"{label}-{i}")
        session.add(ri)
        session.flush()
        session.add(ArticleReport(
            raw_item_id=ri.id, is_product_related=True, title=f"{label} {i}",
            summary=summ, products=["CeraVe"], cluster_id=cluster.id,
        ))
    session.flush()
    return cluster


def test_merge_parse() -> None:
    good = '{"label": "Rose fragrances rising", "summary": "Two outlets agree."}'
    story = MistralMerger.parse(good)
    assert story.label == "Rose fragrances rising"
    assert MistralMerger.parse("nope").label == ""


def test_merge_clusters_multi_and_singleton(db_session) -> None:
    _cluster_with_members(db_session, "multi", ["a summary", "b summary"], size=2)
    _cluster_with_members(db_session, "solo", ["only summary"], size=1)
    merger = FakeMerger(MergedStory(label="Merged story", summary="Combined."))
    stats = merge_clusters(merger, session=db_session)
    assert stats["merged"] == 1 and stats["singletons"] == 1

    multi = db_session.query(ReportCluster).filter_by(size=2).one()
    solo = db_session.query(ReportCluster).filter_by(size=1).one()
    assert multi.summary == "Combined." and multi.label == "Merged story"
    assert solo.summary == "only summary"  # singleton reuses its article summary


def test_render_product_report(db_session) -> None:
    c = _cluster_with_members(db_session, "story", ["s1", "s2"], size=2)
    c.summary = "Merged summary."
    c.label = "Rose fragrances rising"
    db_session.flush()
    md = render_product_report(db_session)
    assert "# NewsPulse — Beauty Product News Report" in md
    assert "Rose fragrances rising" in md
    assert "2 articles merged" in md
    assert "Merged summary." in md
    assert "**Products:** CeraVe" in md
    assert "https://e/story-0" in md  # member citation


def _client(db_session) -> TestClient:
    def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    return TestClient(app)


def test_product_api(db_session) -> None:
    c = _cluster_with_members(db_session, "story", ["s1", "s2"], size=2)
    c.summary = "Merged summary."
    db_session.commit()
    try:
        client = _client(db_session)
        report = client.get("/product-report")
        assert report.status_code == 200 and "Merged summary." in report.text

        clusters = client.get("/product-clusters")
        assert clusters.status_code == 200
        data = clusters.json()
        assert len(data) == 1
        assert data[0]["size"] == 2
        assert len(data[0]["members"]) == 2
        assert data[0]["products"] == ["CeraVe"]
    finally:
        app.dependency_overrides.clear()
