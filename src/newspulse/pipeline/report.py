"""Report generator — render the top Trend Cards for a window as Markdown.

``render_report`` is pure (DB -> markdown string) and is reused by the API's
/report/latest endpoint. ``write_report`` also persists the markdown to object
storage as a report file (the Part 5.2 deliverable).
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newspulse.db import SessionLocal
from newspulse.models import Entity, Trend, TrendCard
from newspulse.storage import ObjectStorage, get_storage


def render_report(session: Session, window: str = "30d", top_n: int = 10) -> str:
    """Render the latest top-N Trend Cards for ``window`` as Markdown ('' if none)."""
    latest = session.execute(
        select(func.max(Trend.computed_at)).where(Trend.window == window)
    ).scalar()
    if latest is None:
        return ""

    rows = session.execute(
        select(Trend, Entity, TrendCard)
        .join(Entity, Entity.id == Trend.entity_id)
        .join(TrendCard, TrendCard.trend_id == Trend.id)
        .where(Trend.window == window, Trend.computed_at == latest)
        .order_by(Trend.rank)
        .limit(top_n)
    ).all()

    lines = [
        f"# NewsPulse — Beauty Trend Report ({window})",
        f"_Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC · snapshot {latest:%Y-%m-%d}_",
        "",
    ]
    if not rows:
        lines.append("_No Trend Cards available for this window yet._")
        return "\n".join(lines)

    for trend, entity, card in rows:
        lines.append(f"## {trend.rank}. {card.title}")
        lines.append(
            f"**{entity.canonical_name}** ({entity.type}) · "
            f"mentions {trend.mention_count} · momentum {trend.momentum_score:.1f}"
        )
        lines.append("")
        lines.append(card.body)
        if card.so_what:
            lines.append("")
            lines.append(f"**So what:** {card.so_what}")
        lines.append("")
        lines.append("**Sources:**")
        for cite in card.citations or []:
            lines.append(f"- [{cite.get('title')}]({cite.get('url')})")
        lines.append("")
    return "\n".join(lines)


def write_report(
    session: Session | None = None,
    window: str = "30d",
    top_n: int = 10,
    storage: ObjectStorage | None = None,
) -> tuple[str, str]:
    """Render and persist the report. Returns (storage_ref, markdown)."""
    own_session = session is None
    session = session or SessionLocal()
    storage = storage or get_storage()
    try:
        markdown = render_report(session, window, top_n)
        ref = storage.put(f"reports/{window}-latest.md", markdown.encode("utf-8"))
        return ref, markdown
    finally:
        if own_session:
            session.close()


def main() -> None:
    ref, markdown = write_report()
    print(f"[report] wrote {ref} ({len(markdown)} chars)")


if __name__ == "__main__":
    main()
