"""Experiment flow router: consent, welcome, priming, instructions, payment."""

import secrets
import uuid
import asyncio
import logging

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from database import get_db
from models.participant import Participant, Step, TaskType
from services import condition_assignment_lock, get_condition_counts, assign_condition
from services import prolific
from services.chat_settings import get_chat_limits
from services.monitoring import log_event, log_step_entry
from services.participant_factory import generate_display_id
from dependencies.participant import (
    AVAILABLE_AVATARS,
    advance_step,
    can_access_payment,
    continue_session,
    get_participant,
    participant_to_dict,
    redirect,
    redirect_to_step,
    require_participant,
    set_session_cookie,
    should_reuse_consent_session,
    start_participant_session,
)
from config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

INSTRUCTIONS_STEPS = {
    Step.instructions_r1: ("r1", 1),
    Step.instructions_r2: ("r2", 2),
}
COMPLETION_CODE = "CAZI0L33"
DUPLICATE_PROLIFIC_ERROR = "You have already participated in this study."


def _template(request: Request, name: str, **context):
    return request.app.state.templates.TemplateResponse(name, {"request": request, **context})


def _welcome_context(participant: Participant, **extra) -> dict:
    # Welcome page exposes the Prolific ID input; include the cleartext value.
    return {
        "p": participant_to_dict(participant, include_prolific_id=True),
        "avatars": AVAILABLE_AVATARS,
        "demo_mode": settings.DEMO_MODE,
        **extra,
    }


async def _advance_existing_consent(
    request: Request,
    participant: Participant,
    db: AsyncSession,
    *,
    prolific_id: str,
    session_id: str,
    study_id: str,
):
    """Keep pre-assigned conditions and move this consent-session participant on."""
    if prolific_id:
        duplicate = await prolific.find_duplicate_participant(
            db, prolific_id, exclude_participant_id=participant.id
        )
        if duplicate:
            if not settings.DEMO_MODE:
                return _template(
                    request,
                    "consent.html",
                    error=DUPLICATE_PROLIFIC_ERROR,
                    prolific_id=prolific_id,
                    session_id=session_id,
                    study_id=study_id,
                )
            logger.warning(
                "Demo: skipping duplicate Prolific ID on consent reuse for %s",
                participant.display_id,
            )
        else:
            prolific.store_on_participant(participant, prolific_id)
            if session_id:
                participant.session_id = session_id
            if study_id:
                participant.study_id = study_id

    logger.info(
        "Consent reuse for %s (test=%s): keeping %s / %s / %s",
        participant.display_id,
        participant.is_test,
        participant.task_type.value,
        participant.partnership.value,
        participant.partner_label.value,
    )
    await advance_step(participant, Step.welcome, db)
    return set_session_cookie(redirect("/welcome"), participant)


# -- Consent ------------------------------------------------

@router.get("/consent", response_class=HTMLResponse)
async def consent_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await get_participant(request, db)
    if participant and participant.current_step != Step.consent:
        return await redirect_to_step(participant, db)

    return _template(
        request,
        "consent.html",
        prolific_id=request.query_params.get("PROLIFIC_PID"),
        session_id=request.query_params.get("SESSION_ID"),
        study_id=request.query_params.get("STUDY_ID"),
    )


@router.post("/consent")
async def consent_submit(
    request: Request,
    consent: str = Form(...),
    prolific_id: str = Form(default=""),
    session_id: str = Form(default=""),
    study_id: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    if consent != "agree":
        return _template(request, "end_no_consent.html")

    existing = await get_participant(request, db)
    if existing and existing.current_step != Step.consent:
        return await redirect_to_step(existing, db)

    prolific_id = prolific.sanitize_prolific_id(prolific_id)

    # Test Tools (and any resumed consent session) already have conditions.
    # Do not insert a new min-quota row or the assigned task_type is lost.
    if should_reuse_consent_session(existing):
        assert existing is not None
        return await _advance_existing_consent(
            request,
            existing,
            db,
            prolific_id=prolific_id,
            session_id=session_id,
            study_id=study_id,
        )

    if prolific_id and await prolific.is_duplicate_participant(db, prolific_id):
        return _template(
            request,
            "consent.html",
            error=DUPLICATE_PROLIFIC_ERROR,
            prolific_id=prolific_id,
            session_id=session_id,
            study_id=study_id,
        )

    # Hold the assignment lock around count read + condition pick + insert so
    # the min-quota allocation cannot lose a row to a concurrent /consent.
    # Also retry inside the lock to absorb any residual display_id collisions.
    async with condition_assignment_lock:
        task_type, partnership, partner_label = assign_condition(
            await get_condition_counts(db)
        )

        last_error: IntegrityError | None = None
        participant: Participant | None = None
        for _ in range(5):
            candidate = Participant(
                display_id=await generate_display_id(db),
                task_type=task_type,
                partnership=partnership,
                partner_label=partner_label,
                current_step=Step.welcome,
                resume_token=secrets.token_urlsafe(48),
            )
            if prolific_id:
                prolific.store_on_participant(candidate, prolific_id)
                candidate.session_id = session_id
                candidate.study_id = study_id

            db.add(candidate)
            try:
                await db.commit()
            except IntegrityError as exc:
                last_error = exc
                await db.rollback()
                if prolific_id and prolific.is_prolific_unique_violation(exc):
                    if settings.DEMO_MODE:
                        # Demo allows reuse of a Prolific ID; retry without storing it
                        # so the unique index cannot 500 the consent page.
                        logger.warning(
                            "Demo: Prolific ID already stored on another participant; "
                            "continuing without attaching it"
                        )
                        prolific_id = ""
                        continue
                    return _template(
                        request,
                        "consent.html",
                        error=DUPLICATE_PROLIFIC_ERROR,
                        prolific_id=prolific_id,
                        session_id=session_id,
                        study_id=study_id,
                    )
                continue
            await db.refresh(candidate)
            participant = candidate
            break
        if participant is None:
            logger.error("Failed to allocate display_id after retries: %s", last_error)
            raise last_error if last_error else RuntimeError("display_id allocation failed")

    await log_event(db, participant.id, "participant_created", "consent", {
        "task_type": task_type.value,
        "partnership": partnership.value,
        "partner_label": partner_label.value,
    })
    await log_step_entry(db, participant.id, Step.welcome.value)

    return set_session_cookie(redirect("/welcome"), participant)


# -- Welcome ------------------------------------------------

@router.get("/welcome", response_class=HTMLResponse)
async def welcome_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant, redirect_resp = await require_participant(request, db, step=Step.welcome)
    if redirect_resp:
        return redirect_resp
    return _template(request, "welcome.html", **_welcome_context(participant))


@router.post("/welcome")
async def welcome_submit(
    request: Request,
    prolific_id: str = Form(default=""),
    avatar: str = Form(...),
    nickname: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    participant, redirect_resp = await require_participant(request, db)
    if redirect_resp:
        return redirect_resp

    prolific_id, error = prolific.validate_for_welcome(prolific_id)
    form_state = {"prolific_id_value": prolific_id, "selected_avatar": avatar, "nickname_value": nickname}
    if error:
        return _template(request, "welcome.html", **_welcome_context(participant, error=error, **form_state))

    if avatar not in AVAILABLE_AVATARS:
        return _template(
            request,
            "welcome.html",
            **_welcome_context(participant, error="Please select a valid avatar.", **form_state),
        )

    nickname = nickname.strip()
    if len(nickname) < 2 or len(nickname) > 20:
        return _template(
            request,
            "welcome.html",
            **_welcome_context(
                participant,
                error="Please enter a nickname between 2 and 20 characters.",
                **form_state,
            ),
        )

    if prolific_id:
        duplicate = await prolific.find_duplicate_participant(
            db, prolific_id, exclude_participant_id=participant.id
        )
        if duplicate:
            if not settings.DEMO_MODE:
                return _template(
                    request,
                    "welcome.html",
                    **_welcome_context(
                        participant, error=DUPLICATE_PROLIFIC_ERROR, **form_state
                    ),
                )
            # Demo: continue the flow but do not write a colliding unique hash.
            logger.warning(
                "Demo: skipping duplicate Prolific ID store for %s",
                participant.display_id,
            )
        else:
            try:
                prolific.store_on_participant(participant, prolific_id)
            except Exception:
                logger.exception("Failed to encrypt/store Prolific ID")
                return _template(
                    request,
                    "welcome.html",
                    **_welcome_context(
                        participant,
                        error="Unable to save your Prolific ID. Please try again.",
                        **form_state,
                    ),
                )

    participant.avatar = avatar
    participant.nickname = nickname
    try:
        await advance_step(participant, Step.priming, db)
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("Welcome submit IntegrityError for %s: %s", participant.display_id, exc)
        error = (
            DUPLICATE_PROLIFIC_ERROR
            if prolific.is_prolific_unique_violation(exc)
            else "Something went wrong. Please try again."
        )
        return _template(
            request,
            "welcome.html",
            **_welcome_context(participant, error=error, **form_state),
        )
    return redirect("/priming")


# -- Priming ------------------------------------------------

@router.get("/priming", response_class=HTMLResponse)
async def priming_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant, redirect_resp = await require_participant(request, db, step=Step.priming)
    if redirect_resp:
        return redirect_resp

    return _template(
        request,
        "priming.html",
        p=participant_to_dict(participant),
        is_emotion=participant.task_type == TaskType.emotionTask,
    )


@router.post("/priming")
async def priming_submit(
    request: Request,
    priming_text: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    participant, redirect_resp = await require_participant(request, db)
    if redirect_resp:
        return redirect_resp

    word_count = len(priming_text.split())
    if word_count < 10:
        return _template(
            request,
            "priming.html",
            p=participant_to_dict(participant),
            is_emotion=participant.task_type == TaskType.emotionTask,
            error=f"Please write at least 10 words. You wrote {word_count}.",
            priming_text=priming_text,
        )

    participant.priming_text = priming_text
    await advance_step(participant, Step.instructions_r1, db)
    return redirect("/instructions")


# -- Instructions -------------------------------------------

@router.get("/instructions", response_class=HTMLResponse)
async def instructions_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant, redirect_resp = await require_participant(request, db)
    if redirect_resp:
        return redirect_resp
    if participant.current_step not in INSTRUCTIONS_STEPS:
        return await redirect_to_step(participant, db)

    variant, round_num = INSTRUCTIONS_STEPS[participant.current_step]
    limits = get_chat_limits()

    return _template(
        request,
        "instructions.html",
        p=participant_to_dict(participant),
        variant=variant,
        round_number=round_num,
        min_turns=limits.min_turns,
        max_turns=limits.max_turns,
        max_duration_minutes=limits.max_duration_minutes,
    )


@router.post("/instructions")
async def instructions_submit(request: Request, db: AsyncSession = Depends(get_db)):
    participant, redirect_resp = await require_participant(request, db)
    if redirect_resp:
        return redirect_resp

    if participant.current_step == Step.instructions_r1:
        await advance_step(participant, Step.chat_r1, db, round_number=1)
    elif participant.current_step == Step.instructions_r2:
        await advance_step(participant, Step.chat_r2, db, round_number=2)
    else:
        return await redirect_to_step(participant, db)

    return redirect("/waiting")


# -- Payment ------------------------------------------------

@router.get("/payment", response_class=HTMLResponse)
async def payment_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant, redirect_resp = await require_participant(request, db)
    if redirect_resp:
        return redirect_resp

    # Finished participants may re-render the payment page; everyone else
    # must already be on Step.payment (set by demographics_submit).
    if not can_access_payment(participant):
        return await redirect_to_step(participant, db)

    if not participant.is_finished:
        participant.is_finished = True
        await db.commit()
        await log_event(db, participant.id, "experiment_completed", "payment")

        # Fire Prolific completion callback once, off the request path.
        # Re-renders of /payment must not retrigger or block on this.
        if participant.session_id and not settings.DEMO_MODE:
            session_id = participant.session_id
            display_id = participant.display_id

            async def _send_completion() -> None:
                try:
                    await prolific.send_prolific_completion(session_id)
                except Exception:
                    logger.warning(
                        "Prolific completion callback failed for %s", display_id
                    )

            asyncio.create_task(_send_completion())

    return _template(
        request,
        "payment.html",
        p=participant_to_dict(participant),
        completion_code=COMPLETION_CODE,
    )


# -- Resume ------------------------------------------------

@router.get("/resume/{token}", response_class=HTMLResponse)
async def resume_session(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Resume participant session via secure token URL."""
    result = await db.execute(select(Participant).where(Participant.resume_token == token))
    if not (participant := result.scalar_one_or_none()):
        return redirect("/consent")
    return await start_participant_session(participant, db)


# -- Entry point --------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def entry(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await get_participant(request, db)
    if not participant:
        return redirect("/consent")
    return await continue_session(participant, db)


@router.get("/experiment/{participant_id}", response_class=HTMLResponse)
async def experiment_entry(participant_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Entry point for test participants (uses UUID in URL instead of cookie).

    Restricted to ``is_test`` participants so a leaked URL cannot grant a
    session cookie for a real respondent.
    """
    try:
        pid = uuid.UUID(participant_id)
    except ValueError:
        return redirect("/consent")

    result = await db.execute(select(Participant).where(Participant.id == pid))
    participant = result.scalar_one_or_none()
    if not participant or not participant.is_test:
        return redirect("/consent")

    return await start_participant_session(participant, db)
