"""069_add_terminology_metric_kind

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-10 20:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'terminology',
        sa.Column('metric_kind', sa.String(length=32), nullable=False, server_default='flow'),
    )
    op.alter_column('terminology', 'metric_kind', server_default=None)


def downgrade():
    op.drop_column('terminology', 'metric_kind')
