"""068_query_earliest_date_variable

Revision ID: b8c9d0e1f2a3
Revises: a1b2c3d4e5f6
Create Date: 2026-05-18 14:00:00.000000

"""

from alembic import op
from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import column, table

revision = "b8c9d0e1f2a3"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    variable_table = table(
        "system_variable",
        column("id", BigInteger),
        column("name", String),
        column("var_type", String),
        column("type", String),
        column("value", JSONB),
        column("create_time", DateTime),
        column("create_by", BigInteger),
    )
    op.bulk_insert(
        variable_table,
        [
            {
                "name": "i18n_variable.query_earliest_date",
                "var_type": "text",
                "type": "system",
                "value": ["2024-01-01"],
                "create_time": None,
                "create_by": None,
            },
        ],
    )


def downgrade():
    op.execute(
        "DELETE FROM system_variable WHERE name = 'i18n_variable.query_earliest_date'"
    )
