"""Product report renderer — merged stories + standalone product articles.

Pure DB -> Markdown (reused by the API); write_product_report also persists it.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newspulse.db import SessionLocal
from newspulse.models import ArticleReport, RawItem, ReportCluster, Source
from newspulse.storage import ObjectStorage, get_storage


def _members(session: Session, cluster_id: int):
    return session.execute(
        select(ArticleReport, RawItem, Source)
        .join(RawItem, RawItem.id == ArticleReport.raw_item_id)
        .join(Source, Source.id == RawItem.source_id)
        .where(ArticleReport.cluster_id == cluster_id)
        .order_by(ArticleReport.id)
    ).all()


def render_product_report(session: Session) -> str:
    """Render clusters (merged stories first) as a Markdown product-news report."""
    clusters = list(
        session.execute(
            select(ReportCluster).order_by(ReportCluster.size.desc(), ReportCluster.id)
        ).scalars().all()
    )
    lines = [
        "# NewsPulse — Beauty Product News Report",
        f"_Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC · {len(clusters)} stories_",
        "",
    ]
    if not clusters:
        lines.append("_No product articles yet._")
        return "\n".join(lines)

    for cluster in clusters:
        members = _members(session, cluster.id)
        heading = cluster.label or "Untitled"
        if cluster.size > 1:
            heading += f"  ·  {cluster.size} articles merged"
        lines.append(f"## {heading}")
        lines.append(cluster.summary or "")

        products = sorted({p for (ar, _, _) in members for p in (ar.products or [])})
        if products:
            lines.append("")
            lines.append("**Products:** " + ", ".join(products[:12]))

        lines.append("")
        lines.append("**Sources:**")
        for _ar, ri, src in members:
            lines.append(f"- [{ri.title}]({ri.url}) — {src.name}")
        lines.append("")
    return "\n".join(lines)


def write_product_report(
    session: Session | None = None, storage: ObjectStorage | None = None
) -> tuple[str, str]:
    own_session = session is None
    session = session or SessionLocal()
    storage = storage or get_storage()
    try:
        markdown = render_product_report(session)
        ref = storage.put("reports/product-latest.md", markdown.encode("utf-8"))
        return ref, markdown
    finally:
        if own_session:
            session.close()
