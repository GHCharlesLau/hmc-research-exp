"""Monitoring service: event logging, step duration tracking, stuck participant detection."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.experiment import ExperimentSession
from models.participant import Participant
from services.matchmaking import get_redis

logger = logging.getLogger(__name__)

# Reasonable time limits per step (seconds).
# Steps not listed have no limit (e.g., chat_r1, chat_r2 have their own timer).
STEP_TIME_LIMITS: dict[str, int] = {
    "consent": 300,
    "welcome": 120,
    "priming": 600,
    "instructions_r1": 120,
    "instructions_r2": 120,
    "survey_prompt": 60,
    "survey_a": 300,
    "survey_b": 300,
    "demographics": 300,
    "payment": 120,
}

# Redis key prefix for step entry timestamps
_STEP_TIME_PREFIX = "step_time:"


async def log_event(
    db: AsyncSession,
    participant_id,
    event: str,
    step: str | None = None,
    metadata: dict | None = None,
) -> ExperimentSession:
    """Log an experiment event to the database."""
    session = ExperimentSession(
        participant_id=participant_id,
        event=event,
        step=step,
        metadata_json=metadata,
    )
    db.add(session)
    await db.commit()
    return session


async def log_step_entry(
    db: AsyncSession,
    participant_id,
    step: str,
    metadata: dict | None = None,
) -> None:
    """Record that a participant entered a step. Also stores timestamp in Redis."""
    now = datetime.now(timezone.utc)

    # Store entry time in Redis for fast duration calculation
    try:
        r = await get_redis()
        key = f"{_STEP_TIME_PREFIX}{participant_id}:{step}"
        await r.setex(key, 86400, now.isoformat())
    except Exception as e:
        logger.warning(f"Failed to store step entry time in Redis: {e}")

    await log_event(db, participant_id, "step_entered", step, {
        **(metadata or {}),
        "entered_at": now.isoformat(),
    })


async def log_step_duration(
    db: AsyncSession,
    participant_id,
    from_step: str,
    to_step: str,
    duration_seconds: float,
) -> None:
    """Record the time spent at a step."""
    limit = STEP_TIME_LIMITS.get(from_step)
    await log_event(db, participant_id, "step_duration", from_step, {
        "from_step": from_step,
        "to_step": to_step,
        "duration_seconds": round(duration_seconds, 1),
        "is_over_limit": duration_seconds > limit if limit else False,
        "time_limit": limit,
    })


async def get_step_entry_time(participant_id, step: str) -> datetime | None:
    """Get the time a participant entered a step from Redis cache."""
    try:
        r = await get_redis()
        key = f"{_STEP_TIME_PREFIX}{participant_id}:{step}"
        val = await r.get(key)
        if val:
            return datetime.fromisoformat(val.decode() if isinstance(val, bytes) else val)
    except Exception as e:
        logger.warning(f"Failed to get step entry time from Redis: {e}")
    return None


async def detect_stuck_participants(db: AsyncSession) -> list[dict]:
    """Find participants who have exceeded time limits on their current step."""
    result = await db.execute(
        select(Participant).where(
            Participant.is_finished == False,
        )
    )
    stuck = []
    now = datetime.now(timezone.utc)
    for p in result.scalars().all():
        step = p.current_step.value
        # Participants at payment page are finished — never stuck
        if step == "payment":
            continue
        limit = STEP_TIME_LIMITS.get(step)
        if not limit:
            continue

        # Check Redis first for speed
        entered_at = await get_step_entry_time(p.id, step)
        if not entered_at:
            continue

        elapsed = (now - entered_at).total_seconds()
        if elapsed > limit:
            stuck.append({
                "display_id": p.display_id,
                "step": step,
                "elapsed_seconds": round(elapsed),
                "limit_seconds": limit,
                "over_by_seconds": round(elapsed - limit),
            })
    return stuck
