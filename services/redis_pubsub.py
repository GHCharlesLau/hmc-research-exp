import asyncio
import json
import logging

import redis.asyncio as aioredis

from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Max consecutive reconnect attempts before giving up
_MAX_RECONNECT_ATTEMPTS = 5
# Seconds to wait between reconnect attempts
_RECONNECT_DELAY = 2


async def create_pubsub() -> aioredis.Redis:
    """Create a dedicated Redis connection for Pub/Sub.

    Note: Pub/Sub requires its own connection; we cannot reuse the shared
    pool from matchmaking.py because once a connection enters subscriber
    mode it can only perform subscribe/unsubscribe commands.
    """
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return r


async def subscribe_and_forward(channel: str, callback) -> None:
    """Subscribe to a Redis channel and forward messages to callback.

    Includes automatic reconnection logic (N9): if the Redis connection
    drops, the subscriber will attempt to reconnect up to
    _MAX_RECONNECT_ATTEMPTS times before giving up.
    """
    for attempt in range(1, _MAX_RECONNECT_ATTEMPTS + 1):
        r = await create_pubsub()
        pubsub = r.pubsub()
        try:
            await pubsub.subscribe(channel)
            logger.info(f"Subscribed to Redis channel: {channel} (attempt {attempt})")

            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    await callback(data)

        except asyncio.CancelledError:
            logger.info(f"Unsubscribed from channel: {channel}")
            await pubsub.unsubscribe(channel)
            await r.aclose()
            return

        except Exception as e:
            logger.error(f"Pub/Sub error on channel {channel}: {e}")
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                pass
            await r.aclose()

            if attempt < _MAX_RECONNECT_ATTEMPTS:
                logger.info(f"Reconnecting to channel {channel} in {_RECONNECT_DELAY}s...")
                await asyncio.sleep(_RECONNECT_DELAY)
            else:
                logger.error(f"Max reconnect attempts ({_MAX_RECONNECT_ATTEMPTS}) reached for channel {channel}")
