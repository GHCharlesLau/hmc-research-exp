from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from models.participant import Participant, TaskType, Partnership, PartnerLabel
import random
import itertools
import logging

logger = logging.getLogger(__name__)

# All 8 conditions from the 2×2×2 factorial
ALL_CONDITIONS = list(itertools.product(TaskType, Partnership, PartnerLabel))

# Quota counters (in-memory, reset on restart)
_condition_counts: dict[tuple[TaskType, Partnership, PartnerLabel], int] = {
    cond: 0 for cond in ALL_CONDITIONS
}


async def get_condition_counts(db: AsyncSession) -> dict[tuple[TaskType, Partnership, PartnerLabel], int]:
    """Load current condition counts from database."""
    counts = {}
    for tt, ps, pl in ALL_CONDITIONS:
        result = await db.execute(
            select(func.count(Participant.id)).where(
                Participant.task_type == tt,
                Participant.partnership == ps,
                Participant.partner_label == pl,
            )
        )
        counts[(tt, ps, pl)] = result.scalar() or 0
    return counts


def assign_condition(counts: dict) -> tuple[TaskType, Partnership, PartnerLabel]:
    """Min-quota strategy: assign to condition with fewest participants."""
    min_count = min(counts.values())
    candidates = [cond for cond, c in counts.items() if c == min_count]
    chosen = random.choice(candidates)
    counts[chosen] += 1
    return chosen
