"""074_chat_record_summary

Revision ID: h4b5c6d7e8f9
Revises: g3a4b5c6d7e8
Create Date: 2026-09-15 19:45:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = 'h4b5c6d7e8f9'
down_revision = 'g3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'chat_record',
        sa.Column('summary', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column('chat_record', 'summary')
