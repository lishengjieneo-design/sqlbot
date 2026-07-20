"""072_extra_prompt_version

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-20 18:45:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'extra_prompt_version',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('prompt_id', sa.BigInteger(), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('change_note', sa.String(length=255), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['prompt_id'], ['extra_prompt.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('prompt_id', 'version_no', name='uq_extra_prompt_version_no'),
    )
    op.create_index('ix_extra_prompt_version_prompt_id', 'extra_prompt_version', ['prompt_id'])

    op.add_column('extra_prompt', sa.Column('published_version_id', sa.BigInteger(), nullable=True))
    op.add_column('extra_prompt', sa.Column('draft_version_id', sa.BigInteger(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(text(
        'SELECT id, prompt, create_time FROM extra_prompt ORDER BY id'
    )).fetchall()
    for row in rows:
        prompt_id, prompt_text, create_time = row[0], row[1], row[2]
        content = prompt_text if prompt_text is not None else ''
        result = conn.execute(
            text(
                """
                INSERT INTO extra_prompt_version
                    (prompt_id, version_no, prompt, change_note, created_by, create_time)
                VALUES
                    (:prompt_id, 1, :prompt, :note, NULL, :create_time)
                RETURNING id
                """
            ),
            {
                'prompt_id': prompt_id,
                'prompt': content,
                'note': 'migration backfill',
                'create_time': create_time,
            },
        )
        version_id = result.scalar()
        conn.execute(
            text(
                """
                UPDATE extra_prompt
                SET published_version_id = :vid, draft_version_id = NULL
                WHERE id = :pid
                """
            ),
            {'vid': version_id, 'pid': prompt_id},
        )


def downgrade():
    op.drop_column('extra_prompt', 'draft_version_id')
    op.drop_column('extra_prompt', 'published_version_id')
    op.drop_index('ix_extra_prompt_version_prompt_id', table_name='extra_prompt_version')
    op.drop_table('extra_prompt_version')
