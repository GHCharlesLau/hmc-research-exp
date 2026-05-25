"""add_unique_constraint_chat_messages_dedup

Revision ID: 89a0b4c02a58
Revises: b70ace7d4d4f
Create Date: 2026-05-15 16:00:40.471081
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '89a0b4c02a58'
down_revision: Union[str, None] = 'b70ace7d4d4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
