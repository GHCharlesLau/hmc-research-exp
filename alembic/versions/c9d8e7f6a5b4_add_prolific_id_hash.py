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
    op.add_column("participants", sa.Column("prolific_id_hash", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_participants_prolific_id_hash"), "participants", ["prolific_id_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_participants_prolific_id_hash"), table_name="participants")
    op.drop_column("participants", "prolific_id_hash")
