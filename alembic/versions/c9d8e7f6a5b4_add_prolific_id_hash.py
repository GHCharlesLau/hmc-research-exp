"""add_prolific_id_hash

Revision ID: c9d8e7f6a5b4
Revises: f1a2b3c4
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9d8e7f6a5b4"
down_revision: Union[str, None] = "f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE participants ADD COLUMN IF NOT EXISTS "
        "prolific_id_hash VARCHAR(64)"
    ))
    op.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_participants_prolific_id_hash "
        "ON participants (prolific_id_hash)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_participants_prolific_id_hash"))
    op.execute(sa.text("ALTER TABLE participants DROP COLUMN IF EXISTS prolific_id_hash"))
