"""Shared chat room lookup, identity, and turn-count helpers."""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.chat import ChatRoom, RoomType, SenderRole
from models.participant import Participant
from services.chat_settings import get_chat_limits
from services.matchmaking import get_hhc_peer_msg_count, get_redis

logger = logging.getLogger(__name__)

CHAT_EXIT_ELIGIBLE_PREFIX = "chat_exit_eligible:"
CHAT_EXIT_ELIGIBLE_TTL = 3600


async def get_active_room(
    db: AsyncSession,
    participant_id: uuid.UUID,
    round_number: int,
) -> ChatRoom | None:
    """Return the active ChatRoom for a participant in the given round."""
    result = await db.execute(
        select(ChatRoom)
        .where(
            ChatRoom.participant_id == participant_id,
            ChatRoom.round_number == round_number,
            ChatRoom.is_active == True,  # noqa: E712
        )
        .order_by(ChatRoom.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def is_force_chatbot(participant: Participant, room: ChatRoom | None = None) -> bool:
    """R2 HMC chats always display as MyBot (timeout fallback or HMC carryover).

    Pairing page has no room yet: no real partner means force chatbot.
    Chat page uses the room type so a missing Redis flag cannot flip back to Tommy.
    """
    if room is not None:
        return participant.current_round == 2 and room.room_type == RoomType.HMC
    return participant.current_round == 2 and participant.partner_id is None


def partner_display_assets(
    *,
    force_chatbot: bool,
    is_r1: bool,
    partner_info: dict | None,
    partner_label: str,
) -> tuple[str, str]:
    """Return (avatar_url, display_name) for the chat partner, including deception rules."""
    if force_chatbot:
        return "/static/avatar/myBot.png", "MyBot"
    if not is_r1 and partner_info:
        return f"/static/avatar/{partner_info['avatar']}", partner_info["nickname"]
    if partner_info and partner_label == "chatbot":
        return "/static/avatar/myBot.png", "MyBot"
    if partner_info:
        return f"/static/avatar/{partner_info['avatar']}", partner_info["nickname"]
    if not is_r1:
        return "/static/avatar/myBot.png", "MyBot"
    if partner_label == "human":
        return "/static/avatar/fox.png", "Tommy"
    return "/static/avatar/myBot.png", "MyBot"


def compute_shared_turns(peer_a_count: int, peer_b_count: int) -> int:
    """Complete turns = min of each participant's message count."""
    return min(peer_a_count, peer_b_count)


def hmc_shared_turns(turn_count: int) -> int:
    """HMC: one exchange is a user message plus an LLM reply."""
    return turn_count // 2


def remaining_chat_seconds(room: ChatRoom, now: datetime | None = None) -> int:
    """Seconds left on the chat timer; 0 if the room has timed out."""
    limits = get_chat_limits()
    remaining = limits.max_duration
    if room.started_at:
        now = now or datetime.now(timezone.utc)
        elapsed = (now - room.started_at).total_seconds()
        remaining = max(0, int(limits.max_duration - elapsed))
    return remaining


async def get_shared_turns(
    room: ChatRoom,
    participant: Participant,
) -> int:
    """Shared turn count for the current room (HMC or HHC)."""
    if room.room_type == RoomType.HMC:
        if room.messages:
            users = sum(1 for m in room.messages if m.sender_role == SenderRole.user)
            partners = sum(1 for m in room.messages if m.sender_role == SenderRole.partner)
            return min(users, partners)
        return hmc_shared_turns(room.turn_count)
    my_msgs = await get_hhc_peer_msg_count(room.room_id, str(participant.id))
    partner_msgs = 0
    if participant.partner_id:
        partner_msgs = await get_hhc_peer_msg_count(
            room.room_id, str(participant.partner_id)
        )
    return compute_shared_turns(my_msgs, partner_msgs)


async def mark_chat_exit_eligible(participant_id: uuid.UUID, round_number: int) -> None:
    """Allow retry/dropout for this participant+round (timeout or partner left)."""
    try:
        r = await get_redis()
        key = f"{CHAT_EXIT_ELIGIBLE_PREFIX}{participant_id}:{round_number}"
        await r.setex(key, CHAT_EXIT_ELIGIBLE_TTL, "1")
    except Exception as e:
        logger.warning("Failed to mark chat-exit eligible: %s", e)


async def is_chat_exit_eligible(participant_id: uuid.UUID, round_number: int) -> bool:
    """True when the server previously recorded a timeout or partner-left."""
    try:
        r = await get_redis()
        key = f"{CHAT_EXIT_ELIGIBLE_PREFIX}{participant_id}:{round_number}"
        return bool(await r.get(key))
    except Exception as e:
        logger.warning("Failed to read chat-exit eligible flag: %s", e)
        return False


async def can_skip_min_turns(
    room: ChatRoom,
    participant: Participant,
    *,
    partner_left: bool,
    is_timeout: bool,
    is_retry: bool,
    is_dropout: bool,
) -> bool:
    """Server-side gate for retry/dropout and timeout/partner-left exits.

    Query params are not trusted for retry/dropout: the room must have timed
    out, or a Redis eligibility flag must have been set when the dialog was shown.
    """
    if not (partner_left or is_timeout or is_retry or is_dropout):
        return False

    timed_out = remaining_chat_seconds(room) <= 0
    if timed_out:
        return True

    flagged = await is_chat_exit_eligible(participant.id, room.round_number)
    if flagged:
        return True

    if is_retry or is_dropout:
        logger.warning(
            "Rejected retry/dropout for %s: no timeout and no eligibility flag",
            participant.display_id,
        )
        return False

    # partner_left / timeout query params without a flag: still require evidence.
    logger.warning(
        "Rejected skip-min-turns for %s: query flag without server evidence",
        participant.display_id,
    )
    return False
