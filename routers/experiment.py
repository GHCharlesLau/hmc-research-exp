"""Experiment flow router: consent, welcome, priming, instructions, payment."""

import secrets
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models.participant import Participant, Step, Partnership, PartnerLabel
from models.experiment import ExperimentSession
from services import get_condition_counts, assign_condition
from services import prolific
from services.monitoring import log_event, log_step_entry, log_step_duration, get_step_entry_time
from config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

AVAILABLE_AVATARS = ["lion.png", "rabbit.png", "tiger.png", "fox.png"]


async def _redirect(participant: Participant, db: AsyncSession | None = None) -> RedirectResponse:
    """Redirect participant to their current step.

    For chat steps, finds and includes the active room_id parameter.
    """
    step_routes = {
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

    url = step_routes.get(participant.current_step, "/")

    # BUG-02 FIX: For chat steps, find active room and include room parameter
    if participant.current_step in (Step.chat_r1, Step.chat_r2):
        if db is not None:
            from sqlalchemy import select
            from models.chat import ChatRoom
            result = await db.execute(
                select(ChatRoom).where(
                    ChatRoom.participant_id == participant.id,
                    ChatRoom.round_number == participant.current_round,
                    ChatRoom.is_active == True,
                ).order_by(ChatRoom.created_at.desc()).limit(1)
            )
            room = result.scalar_one_or_none()
            if room:
                url = f"/chat?room={room.id}"

    return RedirectResponse(url=url, status_code=303)


async def _get_participant(request: Request, db: AsyncSession) -> Participant | None:
    """Get participant from session cookie, return None if not found."""
    pid = request.cookies.get("participant_id")
    if not pid:
        return None
    try:
        result = await db.execute(select(Participant).where(Participant.id == uuid.UUID(pid)))
        return result.scalar_one_or_none()
    except (ValueError, Exception):
        return None


def _participant_to_dict(p: Participant) -> dict:
    """Convert participant to template-safe dict."""
    return {
        "id": str(p.id),
        "display_id": p.display_id,
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
        "partner_label_check": _get_partner_label_check(p),
    }


def _get_partner_label_check(p: Participant) -> str:
    """What the participant was told their partner is."""
    if p.partner_label == PartnerLabel.chatbot:
        return "AI chatbot"
    return "another participant (human)"


async def _generate_display_id(db: AsyncSession) -> str:
    """Generate unique display_id like P-0001.

    BUG-P3 FIX: Use MAX+1 approach (same as admin.py) to handle deletions.
    Unique constraint on display_id provides safety net for races.
    """
    from sqlalchemy import func, Integer
    result = await db.execute(
        select(func.max(
            func.cast(
                func.replace(Participant.display_id, 'P-', ''),
                Integer
            )
        ))
    )
    max_num = result.scalar()
    next_num = (max_num or 0) + 1
    return f"P-{next_num:04d}"


async def _advance_step(
    participant: Participant,
    new_step: Step,
    db: AsyncSession,
    round_number: int | None = None,
) -> None:
    """Advance participant to a new step, logging duration of previous step.

    Args:
        participant: The participant object.
        new_step: The step to advance to.
        db: Database session.
        round_number: If provided, also update current_round.
    """
    old_step = participant.current_step

    if round_number is not None:
        participant.current_round = round_number
    participant.current_step = new_step
    await db.commit()

    # Log entry into the new step (stores timestamp in Redis)
    await log_step_entry(db, participant.id, new_step.value)

    # Log duration of the previous step
    if old_step and old_step != Step.consent:
        entered_at = await get_step_entry_time(participant.id, old_step.value)
        if entered_at:
            duration = (datetime.now(timezone.utc) - entered_at).total_seconds()
            await log_step_duration(db, participant.id, old_step.value, new_step.value, duration)


# ── Consent ────────────────────────────────────────────────

@router.get("/consent", response_class=HTMLResponse)
async def consent_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if participant and participant.current_step != Step.consent:
        return await _redirect(participant, db)

    # Check for Prolific params in URL
    prolific_id = request.query_params.get("PROLIFIC_PID")
    session_id = request.query_params.get("SESSION_ID")
    study_id = request.query_params.get("STUDY_ID")

    return request.app.state.templates.TemplateResponse("consent.html", {
        "request": request,
        "prolific_id": prolific_id,
        "session_id": session_id,
        "study_id": study_id,
    })


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
        return request.app.state.templates.TemplateResponse("end_no_consent.html", {
            "request": request,
        })

    # Check Prolific duplicate (skip in demo mode)
    if prolific_id and not settings.DEMO_MODE:
        encrypted = prolific.encrypt_prolific_id(prolific_id)
        result = await db.execute(
            select(Participant).where(Participant.prolific_id_encrypted == encrypted)
        )
        if result.scalar_one_or_none():
            return request.app.state.templates.TemplateResponse("consent.html", {
                "request": request,
                "error": "You have already participated in this study.",
            })

    # Assign condition
    counts = await get_condition_counts(db)
    task_type, partnership, partner_label = assign_condition(counts)

    # Create participant
    display_id = await _generate_display_id(db)
    participant = Participant(
        display_id=display_id,
        task_type=task_type,
        partnership=partnership,
        partner_label=partner_label,
        current_step=Step.welcome,
        resume_token=secrets.token_urlsafe(48),
    )

    if prolific_id:
        participant.prolific_id_encrypted = encrypted
        participant.session_id = session_id
        participant.study_id = study_id

    db.add(participant)
    await db.commit()
    await db.refresh(participant)

    # Log events
    await log_event(db, participant.id, "participant_created", "consent", {
        "task_type": task_type.value,
        "partnership": partnership.value,
        "partner_label": partner_label.value,
    })
    await log_step_entry(db, participant.id, Step.welcome.value)

    response = RedirectResponse(url="/welcome", status_code=303)
    response.set_cookie("participant_id", str(participant.id), httponly=True, max_age=86400)
    return response


# ── Welcome ────────────────────────────────────────────────

@router.get("/welcome", response_class=HTMLResponse)
async def welcome_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)
    if participant.current_step != Step.welcome:
        return await _redirect(participant, db)

    return request.app.state.templates.TemplateResponse("welcome.html", {
        "request": request,
        "p": _participant_to_dict(participant),
        "avatars": AVAILABLE_AVATARS,
    })


@router.post("/welcome")
async def welcome_submit(
    request: Request,
    avatar: str = Form(...),
    nickname: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    participant.avatar = avatar
    participant.nickname = nickname.strip()
    await _advance_step(participant, Step.priming, db)

    return RedirectResponse(url="/priming", status_code=303)


# ── Priming ────────────────────────────────────────────────

@router.get("/priming", response_class=HTMLResponse)
async def priming_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)
    if participant.current_step != Step.priming:
        return await _redirect(participant, db)

    is_emotion = participant.task_type.value == "emotionTask"

    return request.app.state.templates.TemplateResponse("priming.html", {
        "request": request,
        "p": _participant_to_dict(participant),
        "is_emotion": is_emotion,
    })


@router.post("/priming")
async def priming_submit(
    request: Request,
    priming_text: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    word_count = len(priming_text.split())
    if word_count < 10:
        return request.app.state.templates.TemplateResponse("priming.html", {
            "request": request,
            "p": _participant_to_dict(participant),
            "is_emotion": participant.task_type.value == "emotionTask",
            "error": f"Please write at least 10 words. You wrote {word_count}.",
            "priming_text": priming_text,
        })

    participant.priming_text = priming_text
    await _advance_step(participant, Step.instructions_r1, db)

    return RedirectResponse(url="/instructions", status_code=303)


# ── Instructions ───────────────────────────────────────────

@router.get("/instructions", response_class=HTMLResponse)
async def instructions_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    step_map = {
        Step.instructions_r1: ("r1", 1),
        Step.instructions_r2: ("r2", 2),
    }
    if participant.current_step not in step_map:
        return await _redirect(participant, db)

    variant, round_num = step_map[participant.current_step]
    p = _participant_to_dict(participant)

    # BUG-05 FIX: Pass demo mode values to template
    min_turns = settings.DEMO_MIN_TURNS if settings.DEMO_MODE else settings.MIN_TURNS
    max_turns = settings.DEMO_MAX_TURNS if settings.DEMO_MODE else settings.MAX_TURNS
    max_duration_minutes = (settings.DEMO_MAX_DURATION if settings.DEMO_MODE else settings.MAX_DURATION) // 60

    return request.app.state.templates.TemplateResponse("instructions.html", {
        "request": request,
        "p": p,
        "variant": variant,
        "round_number": round_num,
        "min_turns": min_turns,
        "max_turns": max_turns,
        "max_duration_minutes": max_duration_minutes,
    })


@router.post("/instructions")
async def instructions_submit(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    if participant.current_step == Step.instructions_r1:
        await _advance_step(participant, Step.chat_r1, db, round_number=1)
    elif participant.current_step == Step.instructions_r2:
        await _advance_step(participant, Step.chat_r2, db, round_number=2)
    else:
        return await _redirect(participant, db)

    # All participants go to waiting room (both rounds)
    # Round 1 HMC: fake waiting room (simulated match)
    # Round 2 all: try real HHC matching, fallback to BOT
    return RedirectResponse(url="/waiting", status_code=303)


# ── Payment ────────────────────────────────────────────────

@router.get("/payment", response_class=HTMLResponse)
async def payment_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    completion_code = f"CAZI0L33"

    # Mark participant as finished when they reach payment page
    if not participant.is_finished:
        participant.is_finished = True
        await db.commit()
        await log_event(db, participant.id, "experiment_completed", "payment")

    # Send Prolific completion callback (skip in demo mode)
    if participant.session_id and not settings.DEMO_MODE:
        try:
            await prolific.send_prolific_completion(participant.session_id)
        except Exception:
            logger.warning(f"Prolific completion callback failed for {participant.display_id}")

    return request.app.state.templates.TemplateResponse("payment.html", {
        "request": request,
        "p": _participant_to_dict(participant),
        "completion_code": completion_code,
    })


# ── Resume ────────────────────────────────────────────────

@router.get("/resume/{token}", response_class=HTMLResponse)
async def resume_session(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Resume participant session via secure token URL."""
    result = await db.execute(
        select(Participant).where(Participant.resume_token == token)
    )
    participant = result.scalar_one_or_none()
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    if participant.is_finished or participant.current_step == Step.payment:
        response = RedirectResponse(url="/payment", status_code=303)
    else:
        response = await _redirect(participant, db)

    response.set_cookie("participant_id", str(participant.id), httponly=True, max_age=86400)
    return response


# ── Entry point ────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def entry(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if participant:
        if participant.is_finished or participant.current_step == Step.payment:
            return RedirectResponse(url="/payment", status_code=303)
        return await _redirect(participant, db)
    return RedirectResponse(url="/consent", status_code=303)


@router.get("/experiment/{participant_id}", response_class=HTMLResponse)
async def experiment_entry(participant_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Entry point for test participants (uses UUID in URL instead of cookie)."""
    try:
        pid = uuid.UUID(participant_id)
    except ValueError:
        return RedirectResponse(url="/consent", status_code=303)

    result = await db.execute(select(Participant).where(Participant.id == pid))
    participant = result.scalar_one_or_none()
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    if participant.is_finished or participant.current_step == Step.payment:
        response = RedirectResponse(url="/payment", status_code=303)
    else:
        response = await _redirect(participant, db)

    # Set cookie so subsequent requests work normally
    response.set_cookie("participant_id", str(participant.id), httponly=True, max_age=86400)
    return response
