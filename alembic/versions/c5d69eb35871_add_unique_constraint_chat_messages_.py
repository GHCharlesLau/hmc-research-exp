"""add_unique_constraint_chat_messages_dedup

Revision ID: c5d69eb35871
Revises: 89a0b4c02a58
Create Date: 2026-05-15 16:01:01.509801
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5d69eb35871'
down_revision: Union[str, None] = '89a0b4c02a58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # BUG-23 FIX: Unique constraint prevents duplicate partner messages
    # in HHC chat (same room + sender_role + turn_number = duplicate)
    op.create_unique_constraint(
        'uq_chat_messages_room_role_turn',
        'chat_messages',
        ['chat_room_id', 'sender_role', 'turn_number'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_chat_messages_room_role_turn', 'chat_messages', type_='unique')
