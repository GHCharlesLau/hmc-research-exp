"""add_is_dropout_to_participants

Revision ID: e8f2a1b3c4d5
Revises: 35839de747e2
Create Date: 2026-06-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8f2a1b3c4d5'
down_revision: Union[str, None] = '35839de747e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE participants ADD COLUMN IF NOT EXISTS "
        "is_dropout BOOLEAN NOT NULL DEFAULT false"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE participants DROP COLUMN IF EXISTS is_dropout"
    ))
