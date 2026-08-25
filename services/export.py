import csv
import io
import logging
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.participant import Participant
from models.chat import ChatRoom, ChatMessage, SenderRole
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


async def _build_participant_lookup(db: AsyncSession) -> dict:
    """Build lookup dict: participant UUID -> display_id.

    Loads all participants (including test) so partner resolution
    works even when the export filters out test participants.
    """
    result = await db.execute(select(Participant))
    return {p.id: p.display_id for p in result.scalars().all()}


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
        .options(selectinload(Participant.survey_response), selectinload(Participant.chat_rooms))
        .order_by(Participant.created_at)
    )
    if not include_test:
        query = query.where(Participant.is_test == False)
    result = await db.execute(query)
    participants = result.scalars().all()

    # Build lookup for partner resolution
    participant_lookup = await _build_participant_lookup(db)
    max_duration = get_chat_limits().max_duration

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    header = [
        "display_id", "prolific_id", "task_type", "partnership", "partner_label",
        "partner_display_id",
        "current_round", "hhc_fallback", "is_finished", "is_timeout", "is_dropout",
    ]
    header += _build_survey_header()
    header += [
        "chat_r1_turns", "chat_r1_duration", "chat_r1_over_max",
        "chat_r2_turns", "chat_r2_duration", "chat_r2_over_max",
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

        # Resolve partner display_id
        partner_display_id = ""
        if p.partner_id and p.partner_id in participant_lookup:
            partner_display_id = participant_lookup[p.partner_id]

        sr = p.survey_response
        # Chat stats by round — keep room with most turns per round
        chat_stats = {}
        for room in p.chat_rooms:
            rn = room.round_number
            key_turns = f"r{rn}_turns"
            user_msgs = sum(1 for m in room.messages if m.sender_role == SenderRole.user)
            partner_msgs = sum(1 for m in room.messages if m.sender_role == SenderRole.partner)
            complete_turns = min(user_msgs, partner_msgs)
            if key_turns not in chat_stats or complete_turns > chat_stats[key_turns]:
                chat_stats[f"r{rn}_turns"] = complete_turns
                chat_stats[f"r{rn}_duration"] = room.duration_seconds or 0

        r1_duration = chat_stats.get("r1_duration", "")
        r2_duration = chat_stats.get("r2_duration", "")
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
            p.display_id, prolific_id, p.task_type.value, p.partnership.value,
            p.partner_label.value, partner_display_id,
            p.current_round, p.hhc_fallback, p.is_finished,
            p.is_timeout, p.is_dropout,
        ]
        # Survey data
        if sr:
            row += _build_survey_row(sr)
        else:
            row += [""] * SURVEY_FIELD_COUNT

        row += [
            chat_stats.get("r1_turns", ""), r1_duration, int(r1_over) if r1_duration != "" else "",
            chat_stats.get("r2_turns", ""), r2_duration, int(r2_over) if r2_duration != "" else "",
        ]
        row += [p.created_at.isoformat() if p.created_at else ""]
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
    max_duration = get_chat_limits().max_duration

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "message_id", "display_id", "partner_display_id", "room_id", "round_number",
        "room_type", "task_type", "sender_role", "text",
        "turn_number", "created_at",
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

        partner_display_id = ""
        if participant.partner_id and participant.partner_id in participant_lookup:
            partner_display_id = participant_lookup[participant.partner_id]

        writer.writerow([
            str(msg.id), participant.display_id, partner_display_id,
            room.room_id or "", room.round_number,
            room.room_type.value, participant.task_type.value,
            msg.sender_role.value, msg.text, export_turn,
            msg.created_at.isoformat() if msg.created_at else "",
        ])

    return output.getvalue()
