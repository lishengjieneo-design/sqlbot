"""075_chat_record_field_aliases

Revision ID: i5c6d7e8f9a0
Revises: h4b5c6d7e8f9
Create Date: 2026-09-15 21:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'i5c6d7e8f9a0'
down_revision = 'h4b5c6d7e8f9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'chat_record',
        sa.Column('field_aliases', JSONB(), nullable=True),
    )


def downgrade():
    op.drop_column('chat_record', 'field_aliases')
