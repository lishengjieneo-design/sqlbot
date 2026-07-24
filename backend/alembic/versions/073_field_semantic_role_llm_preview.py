"""073_field_semantic_role_llm_preview

Revision ID: g3a4b5c6d7e8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-24 18:50:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'g3a4b5c6d7e8'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'core_field',
        sa.Column('semantic_role', sa.String(length=32), nullable=True),
    )
    op.add_column(
        'core_table',
        sa.Column('llm_preview', JSONB(), nullable=True),
    )


def downgrade():
    op.drop_column('core_table', 'llm_preview')
    op.drop_column('core_field', 'semantic_role')
