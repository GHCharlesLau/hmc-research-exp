"""Participant session helpers shared by experiment, chat, and survey routers."""

import logging
from datetime import datetime, timezone

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.participant import Participant, PartnerLabel, Step
from services import prolific
from services.auth import parse_participant_cookie, set_participant_cookie
from services.chat_context import get_active_room
from services.monitoring import get_step_entry_time, log_step_duration, log_step_entry

logger = logging.getLogger(__name__)

AVAILABLE_AVATARS = ["lion.png", "rabbit.png", "tiger.png", "fox.png"]

STEP_ROUTES = {
    Step.consent: "/consent",
    Step.welcome: "/welcome",
    Step.priming: "/priming",
    Step.instructions_r1: "/instructions",
    Step.chat_r1: "/chat",
    Step.instructions_r2: "/instructions",
    Step.chat_r2: "/chat",
    Step.survey_prompt: "/survey/prompt",
    Step.survey_a: "/survey/a",
    Step.survey_b: "/survey/b",
    Step.survey_c: "/survey/c",
    Step.demographics: "/survey/demographics",
    Step.payment: "/payment",
}


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=303)


def set_session_cookie(response: RedirectResponse, participant: Participant) -> RedirectResponse:
    return set_participant_cookie(response, participant.id)


async def redirect_to_step(
    participant: Participant,
    db: AsyncSession | None = None,
) -> RedirectResponse:
    """Redirect participant to their current step, including active chat room if needed."""
    url = STEP_ROUTES.get(participant.current_step, "/")

    if participant.current_step in (Step.chat_r1, Step.chat_r2) and db is not None:
        room = await get_active_room(db, participant.id, participant.current_round)
        if room:
            url = f"/chat?room={room.id}"

    return redirect(url)


async def get_participant(request: Request, db: AsyncSession) -> Participant | None:
    """Get participant from session cookie, return None if cookie is absent or malformed.

    Database errors are not swallowed: they propagate so they surface as 500s
    instead of being silently downgraded to "no session" redirects to /consent.
    """
    participant_uuid = parse_participant_cookie(request.cookies.get("participant_id"))
    if not participant_uuid:
        return None
    result = await db.execute(
        select(Participant).where(Participant.id == participant_uuid)
    )
    return result.scalar_one_or_none()


async def require_participant(
    request: Request,
    db: AsyncSession,
    *,
    step: Step | None = None,
) -> tuple[Participant | None, RedirectResponse | None]:
    """Load participant or return a redirect when missing or on the wrong step."""
    participant = await get_participant(request, db)
    if not participant:
        return None, redirect("/consent")
    if step and participant.current_step != step:
        return None, await redirect_to_step(participant, db)
    return participant, None


async def continue_session(participant: Participant, db: AsyncSession) -> RedirectResponse:
    """Resume an existing participant at payment or their current step."""
    if participant.is_finished:
        return redirect("/payment")
    return await redirect_to_step(participant, db)


def can_access_payment(participant: Participant) -> bool:
    """True when the participant has reached the payment step or already finished."""
    return participant.is_finished or participant.current_step == Step.payment


def should_reuse_consent_session(participant: Participant | None) -> bool:
    """True when Consent should keep this row instead of assigning a new condition.

    Test Tools pre-assigns task_type / partnership / partner_label and leaves the
    participant on Step.consent so the tester can click through the page. A new
    insert here would discard those conditions.
    """
    return participant is not None and participant.current_step == Step.consent


def participant_to_dict(p: Participant, *, include_prolific_id: bool = False) -> dict:
    """Convert participant to template-safe dict.

    By default the Fernet-encrypted ``prolific_id`` is *not* decrypted.
    """
    return {
        "id": str(p.id),
        "display_id": p.display_id,
        "prolific_id": (
            prolific.decrypt_prolific_id_safe(p.prolific_id_encrypted)
            if include_prolific_id
            else ""
        ),
        "task_type": p.task_type.value,
        "partnership": p.partnership.value,
        "partner_label": p.partner_label.value,
        "current_step": p.current_step.value,
        "current_round": p.current_round,
        "is_finished": p.is_finished,
        "avatar": p.avatar,
        "nickname": p.nickname,
        "chatbot_identity": p.chatbot_identity,
        "chatbot_avatar": p.chatbot_avatar,
        "hhc_fallback": p.hhc_fallback,
        "partner_label_check": (
            "AI chatbot" if p.partner_label == PartnerLabel.chatbot else "another participant (human)"
        ),
    }


async def advance_step(
    participant: Participant,
    new_step: Step,
    db: AsyncSession,
    round_number: int | None = None,
) -> None:
    """Advance participant to a new step, logging duration of the previous step."""
    old_step = participant.current_step

    if round_number is not None:
        participant.current_round = round_number
    participant.current_step = new_step
    participant_id = participant.id
    await db.commit()

    # Monitoring must not fail the user-facing step transition.
    try:
        await log_step_entry(db, participant_id, new_step.value)

        if old_step and old_step != Step.consent:
            entered_at = await get_step_entry_time(participant_id, old_step.value)
            if entered_at:
                duration = (datetime.now(timezone.utc) - entered_at).total_seconds()
                await log_step_duration(
                    db, participant_id, old_step.value, new_step.value, duration
                )
    except Exception:
        logger.exception("Failed to log step transition to %s", new_step.value)


async def start_participant_session(participant: Participant, db: AsyncSession) -> RedirectResponse:
    """Set session cookie and redirect to the participant's current step."""
    return set_session_cookie(await continue_session(participant, db), participant)
