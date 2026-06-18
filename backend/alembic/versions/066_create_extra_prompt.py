"""066_create_extra_prompt

Revision ID: 2f3a7f0f1b2c
Revises: 8ff90df7871d
Create Date: 2026-04-27 19:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "2f3a7f0f1b2c"
down_revision = "8ff90df7871d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "extra_prompt",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("oid", sa.BigInteger(), nullable=True),
        sa.Column("datasource_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("create_time", sa.DateTime(), nullable=True),
        sa.Column("update_time", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extra_prompt_unique_oid_ds_type",
        "extra_prompt",
        ["oid", "datasource_id", "type"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_extra_prompt_unique_oid_ds_type", table_name="extra_prompt")
    op.drop_table("extra_prompt")

