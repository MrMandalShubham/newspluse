"""article_report intel fields (event_types, importance_score, country)

Revision ID: 7a1c2e4b9d33
Revises: 35bf693c48a1
Create Date: 2026-09-08 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7a1c2e4b9d33'
down_revision: str | None = '35bf693c48a1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('article_reports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('event_types', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('importance_score', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('country', sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('article_reports', schema=None) as batch_op:
        batch_op.drop_column('country')
        batch_op.drop_column('importance_score')
        batch_op.drop_column('event_types')
