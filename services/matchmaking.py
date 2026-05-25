import asyncio
import json
import time
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Redis key prefix for matchmaking queue
MATCH_QUEUE_PREFIX = "matchmaking:queue:"

# Pub/Sub channels
MATCH_CHANNEL = "matchmaking:events"
CHAT_CHANNEL_PREFIX = "chat:room:"


# ── Redis connection pool (N3: connection pooling) ────────────

_redis_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Return a shared Redis connection pool."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True, max_connections=20,
        )
    return _redis_pool


# ── Lua script for atomic matching (N2: race condition fix) ──

_MATCH_LUA = """
local key = KEYS[1]
local members = redis.call('ZRANGE', key, 0, 1)
if #members >= 2 then
    redis.call('ZREM', key, members[1], members[2])
    return members
end
return nil
"""

_lua_script: aioredis.Redis | None = None


async def _get_lua_script(r: aioredis.Redis) -> object:
    """Register and return the cached Lua script."""
    global _lua_script
    if _lua_script is None:
        _lua_script = r.register_script(_MATCH_LUA)
    return _lua_script


async def enqueue_match(participant_id: str, round_number: int, task_type: str = "") -> None:
    """Add participant to matchmaking queue with timestamp as score.

    Queue is separated by task_type so emotionTask and functionTask
    participants are only matched within their own type.
    """
    r = await get_redis()
    key = f"{MATCH_QUEUE_PREFIX}{task_type}:round_{round_number}"
    await r.zadd(key, {participant_id: time.time()})
    logger.info(f"Participant {participant_id} enqueued for round {round_number} (task={task_type})")


async def dequeue_match(participant_id: str, round_number: int, task_type: str = "") -> None:
    """Remove participant from matchmaking queue."""
    r = await get_redis()
    key = f"{MATCH_QUEUE_PREFIX}{task_type}:round_{round_number}"
    await r.zrem(key, participant_id)


async def try_match(round_number: int, task_type: str = "") -> tuple[str, str] | None:
    """Atomically pair the two earliest participants in the queue.

    Uses a Redis Lua script to prevent race conditions when multiple
    WebSocket connections call try_match concurrently.
    """
    r = await get_redis()
    key = f"{MATCH_QUEUE_PREFIX}{task_type}:round_{round_number}"
    script = await _get_lua_script(r)
    members = await script(keys=[key])
    if members and len(members) >= 2:
        p1, p2 = members[0], members[1]
        logger.info(f"Matched {p1} and {p2} for round {round_number} (task={task_type})")
        return (p1, p2)
    return None


async def get_queue_position(participant_id: str, round_number: int, task_type: str = "") -> int:
    """Return 1-based position of participant in queue (0 if not found)."""
    r = await get_redis()
    key = f"{MATCH_QUEUE_PREFIX}{task_type}:round_{round_number}"
    rank = await r.zrank(key, participant_id)
    return (rank + 1) if rank is not None else 0


async def publish_match_event(event_type: str, data: dict) -> None:
    """Publish matchmaking event to Redis Pub/Sub."""
    r = await get_redis()
    await r.publish(MATCH_CHANNEL, json.dumps({"type": event_type, **data}))


async def publish_chat_message(room_id: str, message: dict) -> None:
    """Publish chat message to room-specific channel."""
    r = await get_redis()
    await r.publish(f"{CHAT_CHANNEL_PREFIX}{room_id}", json.dumps(message))


async def get_queue_size(round_number: int, task_type: str = "") -> int:
    """Return the number of participants waiting in the queue."""
    r = await get_redis()
    key = f"{MATCH_QUEUE_PREFIX}{task_type}:round_{round_number}"
    return await r.zcard(key)


# ── Match result notification (cross-participant) ───────────

MATCH_RESULT_PREFIX = "matchmaking:result:"


async def set_match_result(participant_id: str, room_uuid: str, room_id: str) -> None:
    """Store match result so the OTHER participant's polling loop can find it."""
    r = await get_redis()
    await r.setex(
        f"{MATCH_RESULT_PREFIX}{participant_id}", 120,
        json.dumps({"room_uuid": room_uuid, "room_id": room_id}),
    )


async def get_match_result(participant_id: str) -> dict | None:
    """Check if this participant has been matched by another's handler."""
    r = await get_redis()
    data = await r.get(f"{MATCH_RESULT_PREFIX}{participant_id}")
    if data:
        await r.delete(f"{MATCH_RESULT_PREFIX}{participant_id}")
        return json.loads(data)
    return None


# ── HHC shared turn counting (N6) ──────────────────────────

HHC_MSG_COUNT_PREFIX = "hhc_msg_count:"
# Per-participant message count: 1 turn = each participant sends at least 1 message
HHC_PEER_MSG_PREFIX = "hhc_peer_msg:"


async def incr_hhc_message_count(room_id: str) -> int:
    """Increment shared message count for an HHC room, return new count.

    This counter is shared by both participants and used as a unique
    turn_number per message (for frontend dedup). It is NOT used for
    the displayed turn count.
    """
    r = await get_redis()
    return await r.incr(f"{HHC_MSG_COUNT_PREFIX}{room_id}")


async def get_hhc_message_count(room_id: str) -> int:
    """Get current shared message count for an HHC room."""
    r = await get_redis()
    count = await r.get(f"{HHC_MSG_COUNT_PREFIX}{room_id}")
    return int(count) if count else 0


async def incr_hhc_peer_msg_count(room_id: str, participant_id: str) -> int:
    """Increment per-participant message count. Returns this participant's count.

    Used to compute complete_turns = min(A_count, B_count).
    """
    r = await get_redis()
    key = f"{HHC_PEER_MSG_PREFIX}{room_id}:{participant_id}"
    return await r.incr(key)


async def get_hhc_peer_msg_count(room_id: str, participant_id: str) -> int:
    """Get per-participant message count."""
    r = await get_redis()
    key = f"{HHC_PEER_MSG_PREFIX}{room_id}:{participant_id}"
    count = await r.get(key)
    return int(count) if count else 0


async def get_all_queue_members() -> dict[str, list[str]]:
    """Return all matchmaking queue members grouped by queue key.

    For admin test tools: shows who is waiting in each queue.
    """
    r = await get_redis()
    result = {}
    # Scan for all matchmaking queue keys
    async for key in r.scan_iter(f"{MATCH_QUEUE_PREFIX}*"):
        members = await r.zrange(key, 0, -1)
        # Strip prefix to get readable queue name
        queue_name = key.removeprefix(MATCH_QUEUE_PREFIX)
        result[queue_name] = members
    return result


async def clear_queue(queue_name: str) -> int:
    """Remove all members from a matchmaking queue. Returns removed count."""
    r = await get_redis()
    key = f"{MATCH_QUEUE_PREFIX}{queue_name}"
    count = await r.zcard(key)
    await r.delete(key)
    return count
