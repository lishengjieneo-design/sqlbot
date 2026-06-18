"""067_chat_record_clarification

Revision ID: a1b2c3d4e5f6
Revises: 2f3a7f0f1b2c
Create Date: 2026-05-18 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "a1b2c3d4e5f6"
down_revision = "2f3a7f0f1b2c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_record", sa.Column("clarification", JSONB, nullable=True))
    op.add_column(
        "chat_record",
        sa.Column("clarification_resolved", sa.Boolean(), nullable=True, server_default=sa.false()),
    )
    op.add_column(
        "chat_record",
        sa.Column("clarification_abandoned", sa.Boolean(), nullable=True, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("chat_record", "clarification_abandoned")
    op.drop_column("chat_record", "clarification_resolved")
    op.drop_column("chat_record", "clarification")
