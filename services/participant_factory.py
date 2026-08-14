"""Shared participant ID allocation used by consent and admin test tools."""

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.participant import Participant


async def generate_display_id(db: AsyncSession) -> str:
    """Generate unique display_id like P-0001.

    Computes ``MAX(display_id) + 1``. This is racy under concurrent inserts;
    callers must wrap the generate-and-commit in a retry loop that handles
    ``IntegrityError`` from the unique constraint on ``display_id``.
    """
    result = await db.execute(
        select(func.max(
            func.cast(func.replace(Participant.display_id, "P-", ""), Integer)
        ))
    )
    return f"P-{(result.scalar() or 0) + 1:04d}"
