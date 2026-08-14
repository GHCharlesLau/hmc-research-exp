import asyncio
import itertools
import logging
import random

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.participant import Participant, PartnerLabel, Partnership, TaskType

logger = logging.getLogger(__name__)

# All 8 conditions from the 2x2x2 factorial.
ALL_CONDITIONS = list(itertools.product(TaskType, Partnership, PartnerLabel))

# Single-worker deploy (see AGENTS.md "Single worker constraint"): an asyncio
# lock is enough to serialize "read counts -> pick min -> insert participant"
# so two concurrent /consent submissions cannot land in the same cell.
condition_assignment_lock = asyncio.Lock()


async def get_condition_counts(db: AsyncSession) -> dict[tuple[TaskType, Partnership, PartnerLabel], int]:
    """Load current condition counts from database."""
    counts = {}
    for tt, ps, pl in ALL_CONDITIONS:
        result = await db.execute(
            select(func.count(Participant.id)).where(
                Participant.task_type == tt,
                Participant.partnership == ps,
                Participant.partner_label == pl,
                Participant.is_test == False,  # noqa: E712
            )
        )
        counts[(tt, ps, pl)] = result.scalar() or 0
    return counts


def assign_condition(counts: dict) -> tuple[TaskType, Partnership, PartnerLabel]:
    """Min-quota strategy: assign to condition with fewest participants.

    Pure function over the supplied counts dict; mutation is intentionally
    avoided here because the source of truth is the database. Callers must
    hold ``condition_assignment_lock`` while reading counts, calling this
    function, and committing the resulting participant row, otherwise two
    concurrent submissions can both observe the same min and target the
    same cell.
    """
    min_count = min(counts.values())
    candidates = [cond for cond, c in counts.items() if c == min_count]
    return random.choice(candidates)
