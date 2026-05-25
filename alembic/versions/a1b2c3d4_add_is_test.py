"""add is_test to participants

Revision ID: a1b2c3d4e5f6
Revises: 1326884a362c
Create Date: 2026-04-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '1326884a362c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('participants', sa.Column('is_test', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('participants', 'is_test')
