import csv
import io
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.participant import Participant
from models.chat import ChatRoom, ChatMessage, SenderRole, RoomType
from models.survey import SurveyResponse
from services.prolific import decrypt_prolific_id
from services.chat_settings import get_chat_limits
from services.scales import (
    LIKERT_SCALES, CUSTOM_ITEMS, CUSTOM_ITEM_EXPORT_MAP,
    get_total_likert_count, DEMOGRAPHICS_STRUCTURAL_FIELDS,
)

logger = logging.getLogger(__name__)

# Total survey fields: Likert scales + custom items + structural demographics
SURVEY_FIELD_COUNT = get_total_likert_count() + len(CUSTOM_ITEMS) + DEMOGRAPHICS_STRUCTURAL_FIELDS


def duration_over_max(duration_seconds: float | int | None, max_duration: int) -> bool:
    """True when a chat lasted at least the configured max duration."""
    if duration_seconds is None:
        return False
    try:
        return float(duration_seconds) >= float(max_duration)
    except (TypeError, ValueError):
        return False


def should_exclude_from_export(
    *,
    is_timeout: bool = False,
    is_dropout: bool = False,
    r1_over_max: bool = False,
    r2_over_max: bool = False,
    exclude_timeout: bool = False,
    exclude_dropout: bool = False,
    exclude_over_max: bool = False,
) -> bool:
    """True when this participant should be omitted from a filtered export."""
    if exclude_timeout and is_timeout:
        return True
    if exclude_dropout and is_dropout:
        return True
    if exclude_over_max and (r1_over_max or r2_over_max):
        return True
    return False


def format_export_timestamp(dt: datetime | None) -> str:
    """Excel-safe UTC timestamp. ISO offsets like +00:00 are treated as formulas."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return f'="{dt.strftime("%Y-%m-%d %H:%M:%S")}"'


def _complete_turns(room: ChatRoom) -> int:
    user_msgs = sum(1 for m in room.messages if m.sender_role == SenderRole.user)
    partner_msgs = sum(1 for m in room.messages if m.sender_role == SenderRole.partner)
    return min(user_msgs, partner_msgs)


def _room_created_at(room: ChatRoom) -> datetime:
    if room.created_at is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if room.created_at.tzinfo is None:
        return room.created_at.replace(tzinfo=timezone.utc)
    return room.created_at


def best_room_for_round(rooms: list[ChatRoom], round_number: int) -> ChatRoom | None:
    """Room with the most complete turns in this round; ties prefer the later room."""
    candidates = [r for r in rooms if r.round_number == round_number]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (_complete_turns(r), _room_created_at(r)))


def partner_display_for_room(
    room: ChatRoom,
    participant_id,
    room_members: dict[str, dict],
    participant_lookup: dict,
) -> str:
    """Human partner display_id for this room. Empty for HMC / AI chats."""
    if room.room_type == RoomType.HHC and room.room_id:
        members = room_members.get(room.room_id) or {}
        for pid, display_id in members.items():
            if pid != participant_id and display_id:
                return display_id
    if room.partner_id and room.partner_id in participant_lookup:
        return participant_lookup[room.partner_id]
    return ""


async def _build_participant_lookup(db: AsyncSession) -> dict:
    """Build lookup dict: participant UUID -> display_id.

    Loads all participants (including test) so partner resolution
    works even when the export filters out test participants.
    """
    result = await db.execute(select(Participant))
    return {p.id: p.display_id for p in result.scalars().all()}


async def _build_hhc_room_members(
    db: AsyncSession, participant_lookup: dict,
) -> dict[str, dict]:
    """Map shared HHC room_id -> {participant_id: display_id}."""
    result = await db.execute(
        select(ChatRoom.room_id, ChatRoom.participant_id).where(ChatRoom.room_id.isnot(None))
    )
    members: dict[str, dict] = {}
    for room_id, pid in result.all():
        if not room_id:
            continue
        members.setdefault(room_id, {})[pid] = participant_lookup.get(pid, "")
    return members


def _build_survey_header() -> list[str]:
    """Build survey CSV header from scale registry."""
    header: list[str] = []

    # Page A Likert scales
    for scale in LIKERT_SCALES:
        if scale.page == "A":
            header.extend(scale.field_names)

    # Page B custom items (with optional rename)
    for ci in CUSTOM_ITEMS:
        if ci.page == "B":
            header.append(CUSTOM_ITEM_EXPORT_MAP.get(ci.field_name, ci.field_name))

    # Page B Likert scales
    for scale in LIKERT_SCALES:
        if scale.page == "B":
            header.extend(scale.field_names)

    # Page C Likert scales (outcome variables)
    for scale in LIKERT_SCALES:
        if scale.page == "C":
            header.extend(scale.field_names)

    # Demographics structural fields
    header.extend(["age", "gender", "race", "education", "partisanship"])

    # Demographics Likert scales
    for scale in LIKERT_SCALES:
        if scale.page == "demographics":
            header.extend(scale.field_names)

    return header


def _build_survey_row(sr: SurveyResponse) -> list:
    """Build survey data row from a SurveyResponse object."""
    row: list = []

    # Page A Likert scales
    for scale in LIKERT_SCALES:
        if scale.page == "A":
            row.extend([getattr(sr, fn) for fn in scale.field_names])

    # Page B custom items
    for ci in CUSTOM_ITEMS:
        if ci.page == "B":
            row.append(getattr(sr, ci.field_name))

    # Page B Likert scales
    for scale in LIKERT_SCALES:
        if scale.page == "B":
            row.extend([getattr(sr, fn) for fn in scale.field_names])

    # Page C Likert scales (outcome variables)
    for scale in LIKERT_SCALES:
        if scale.page == "C":
            row.extend([getattr(sr, fn) for fn in scale.field_names])

    # Demographics structural fields
    row.extend([sr.age, sr.gender, sr.race, sr.education, sr.partisanship])

    # Demographics Likert scales
    for scale in LIKERT_SCALES:
        if scale.page == "demographics":
            row.extend([getattr(sr, fn) for fn in scale.field_names])

    return row


async def export_participant_table(
    db: AsyncSession,
    *,
    include_test: bool = False,
    exclude_timeout: bool = False,
    exclude_dropout: bool = False,
    exclude_over_max: bool = False,
) -> str:
    """Export one row per participant (wide format).

    Args:
        include_test: If False (default), exclude test participants (is_test=True).
        exclude_timeout: Drop participants flagged is_timeout (page idle or incomplete timed-out chat).
        exclude_dropout: Drop participants who chose to leave after a failed chat.
        exclude_over_max: Drop participants whose chat duration reached max_duration.
    """
    query = (
        select(Participant)
        .options(
            selectinload(Participant.survey_response),
            selectinload(Participant.chat_rooms).selectinload(ChatRoom.messages),
        )
        .order_by(Participant.created_at)
    )
    if not include_test:
        query = query.where(Participant.is_test == False)
    result = await db.execute(query)
    participants = result.scalars().all()

    # Build lookup for per-round partner resolution (shared HHC room_id, not Participant.partner_id)
    participant_lookup = await _build_participant_lookup(db)
    room_members = await _build_hhc_room_members(db, participant_lookup)
    max_duration = get_chat_limits().max_duration

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    header = [
        "display_id", "nickname", "avatar", "prolific_id",
        "task_type", "partnership", "partner_label",
        "partner_display_id_r1", "partner_display_id_r2",
        "current_round", "hhc_fallback", "is_finished", "is_timeout", "is_dropout",
    ]
    header += _build_survey_header()
    header += [
        "chat_r1_turns", "chat_r1_duration", "chat_r1_over_max", "chat_r1_room_type",
        "chat_r2_turns", "chat_r2_duration", "chat_r2_over_max", "chat_r2_room_type",
    ]
    header += ["created_at"]
    writer.writerow(header)

    for p in participants:
        prolific_id = ""
        if p.prolific_id_encrypted:
            try:
                prolific_id = f'="{decrypt_prolific_id(p.prolific_id_encrypted)}"'
            except Exception:
                prolific_id = "DECRYPT_ERROR"

        r1_room = best_room_for_round(p.chat_rooms, 1)
        r2_room = best_room_for_round(p.chat_rooms, 2)
        partner_r1 = (
            partner_display_for_room(r1_room, p.id, room_members, participant_lookup)
            if r1_room else ""
        )
        partner_r2 = (
            partner_display_for_room(r2_room, p.id, room_members, participant_lookup)
            if r2_room else ""
        )

        sr = p.survey_response
        r1_turns = _complete_turns(r1_room) if r1_room else ""
        r2_turns = _complete_turns(r2_room) if r2_room else ""
        r1_duration = (r1_room.duration_seconds or 0) if r1_room else ""
        r2_duration = (r2_room.duration_seconds or 0) if r2_room else ""
        r1_over = duration_over_max(r1_duration or None, max_duration)
        r2_over = duration_over_max(r2_duration or None, max_duration)
        if should_exclude_from_export(
            is_timeout=p.is_timeout,
            is_dropout=p.is_dropout,
            r1_over_max=r1_over,
            r2_over_max=r2_over,
            exclude_timeout=exclude_timeout,
            exclude_dropout=exclude_dropout,
            exclude_over_max=exclude_over_max,
        ):
            continue

        row = [
            p.display_id, p.nickname or "", p.avatar or "", prolific_id,
            p.task_type.value, p.partnership.value, p.partner_label.value,
            partner_r1, partner_r2,
            p.current_round, p.hhc_fallback, p.is_finished,
            p.is_timeout, p.is_dropout,
        ]
        if sr:
            row += _build_survey_row(sr)
        else:
            row += [""] * SURVEY_FIELD_COUNT

        row += [
            r1_turns, r1_duration, int(r1_over) if r1_room else "",
            r1_room.room_type.value if r1_room else "",
            r2_turns, r2_duration, int(r2_over) if r2_room else "",
            r2_room.room_type.value if r2_room else "",
        ]
        row += [format_export_timestamp(p.created_at)]
        writer.writerow(row)

    return output.getvalue()


async def export_chat_messages(
    db: AsyncSession,
    *,
    include_test: bool = False,
    exclude_timeout: bool = False,
    exclude_dropout: bool = False,
    exclude_over_max: bool = False,
) -> str:
    """Export one row per chat message (long format).

    Args:
        include_test: If False (default), exclude messages from test participants.
    """
    query = (
        select(ChatMessage)
        .join(ChatRoom)
        .join(Participant)
        .options(
            selectinload(ChatMessage.chat_room).selectinload(
                ChatRoom.participant
            )
        )
        .order_by(ChatMessage.chat_room_id, ChatMessage.created_at)
    )
    if not include_test:
        query = query.where(Participant.is_test == False)

    result = await db.execute(query)
    messages = result.scalars().all()

    # Build lookup for partner resolution
    participant_lookup = await _build_participant_lookup(db)
    room_members = await _build_hhc_room_members(db, participant_lookup)
    max_duration = get_chat_limits().max_duration

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # timestamp sits before free-text so Excel does not swallow it into `text`
    writer.writerow([
        "message_id", "timestamp", "display_id", "nickname", "avatar",
        "partner_display_id", "room_id", "round_number",
        "room_type", "task_type", "sender_role", "turn_number", "text",
    ])

    # Group messages by room, then write with exchange-based turn counting.
    current_room_id = None
    prev_sender = None
    sender_changes = 0

    for msg in messages:
        if msg.chat_room_id != current_room_id:
            current_room_id = msg.chat_room_id
            prev_sender = None
            sender_changes = 0

        if prev_sender is not None and msg.sender_role != prev_sender:
            sender_changes += 1
        prev_sender = msg.sender_role

        export_turn = sender_changes // 2 + 1

        room = msg.chat_room
        participant = room.participant
        room_over_max = duration_over_max(room.duration_seconds, max_duration)
        if should_exclude_from_export(
            is_timeout=participant.is_timeout,
            is_dropout=participant.is_dropout,
            r1_over_max=room_over_max,
            r2_over_max=False,
            exclude_timeout=exclude_timeout,
            exclude_dropout=exclude_dropout,
            exclude_over_max=exclude_over_max,
        ):
            continue

        partner_display_id = partner_display_for_room(
            room, participant.id, room_members, participant_lookup,
        )

        writer.writerow([
            str(msg.id),
            format_export_timestamp(msg.created_at),
            participant.display_id,
            participant.nickname or "",
            participant.avatar or "",
            partner_display_id,
            room.room_id or "",
            room.round_number,
            room.room_type.value,
            participant.task_type.value,
            msg.sender_role.value,
            export_turn,
            msg.text,
        ])

    return output.getvalue()
