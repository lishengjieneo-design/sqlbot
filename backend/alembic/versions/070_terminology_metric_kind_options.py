"""070_terminology_metric_kind_options

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-20 16:45:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import BigInteger, Boolean, Integer, String, text
from sqlalchemy.sql import table, column

revision = 'd0e1f2a3b4c5'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None

BUILTIN_KINDS = [
    ('flow', '发生型指标', 10),
    ('balance', '余额型指标', 20),
    ('org_dimension', '组织维度', 30),
    ('product_dimension', '产品维度', 40),
]


def upgrade():
    op.create_table(
        'terminology_metric_kind',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('oid', sa.BigInteger(), nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('label', sa.String(length=64), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('builtin', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('create_time', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('oid', 'code', name='uq_terminology_metric_kind_oid_code'),
    )
    op.create_index('ix_terminology_metric_kind_oid', 'terminology_metric_kind', ['oid'])

    conn = op.get_bind()
    oid_rows = conn.execute(text(
        """
        SELECT DISTINCT oid FROM (
            SELECT oid FROM terminology WHERE oid IS NOT NULL
            UNION
            SELECT id AS oid FROM sys_workspace
            UNION
            SELECT 1 AS oid
        ) t
        """
    )).fetchall()
    oids = sorted({int(r[0]) for r in oid_rows if r[0] is not None})
    if not oids:
        oids = [1]

    kind_table = table(
        'terminology_metric_kind',
        column('oid', BigInteger),
        column('code', String),
        column('label', String),
        column('sort_order', Integer),
        column('enabled', Boolean),
        column('builtin', Boolean),
        column('create_time', sa.DateTime),
    )
    rows = []
    for oid in oids:
        for code, label, sort_order in BUILTIN_KINDS:
            rows.append({
                'oid': oid,
                'code': code,
                'label': label,
                'sort_order': sort_order,
                'enabled': True,
                'builtin': True,
                'create_time': None,
            })
    if rows:
        op.bulk_insert(kind_table, rows)


def downgrade():
    op.drop_index('ix_terminology_metric_kind_oid', table_name='terminology_metric_kind')
    op.drop_table('terminology_metric_kind')
