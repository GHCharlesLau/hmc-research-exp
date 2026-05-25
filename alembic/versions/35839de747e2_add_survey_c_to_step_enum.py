"""add_survey_c_to_step_enum

Revision ID: 35839de747e2
Revises: dec313396353
Create Date: 2026-05-25 22:16:30.661714
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '35839de747e2'
down_revision: Union[str, None] = 'dec313396353'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE step ADD VALUE IF NOT EXISTS 'survey_c'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values
    pass
