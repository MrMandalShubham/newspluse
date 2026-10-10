"""Add scraper_class, feed_url, query, gl, hl, enabled, last_success_at, last_error to sources

Revision ID: a3f7b2c91d45
Revises: 7a1c2e4b9d33
Create Date: 2026-10-10 04:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3f7b2c91d45'
down_revision: str | None = '7a1c2e4b9d33'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('sources', sa.Column('scraper_class', sa.String(20), nullable=True))
    op.add_column('sources', sa.Column('feed_url', sa.String(1000), nullable=True))
    op.add_column('sources', sa.Column('query', sa.Text(), nullable=True))
    op.add_column('sources', sa.Column('gl', sa.String(10), nullable=True))
    op.add_column('sources', sa.Column('hl', sa.String(10), nullable=True))
    op.add_column('sources', sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('sources', sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sources', sa.Column('last_error', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('sources', 'last_error')
    op.drop_column('sources', 'last_success_at')
    op.drop_column('sources', 'enabled')
    op.drop_column('sources', 'hl')
    op.drop_column('sources', 'gl')
    op.drop_column('sources', 'query')
    op.drop_column('sources', 'feed_url')
    op.drop_column('sources', 'scraper_class')
