"""Admin router: login, dashboard, participants, config, export."""

import hashlib
import secrets
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from database import get_db
from models.participant import Participant, Step, TaskType, Partnership, PartnerLabel
from models.chat import ChatRoom, RoomType
from models.experiment import ExperimentConfig, ExperimentSession
from services.export import export_participant_table, export_chat_messages
from services.matchmaking import get_redis, dequeue_match, set_match_result
from services.monitoring import detect_stuck_participants
from config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


def _verify_password(password: str) -> bool:
    """Verify admin password against stored hash."""
    if not settings.ADMIN_PASSWORD_HASH:
        return False
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    return pwd_hash == settings.ADMIN_PASSWORD_HASH


async def _verify_admin_session(request: Request) -> JSONResponse | None:
    """Verify admin session for API endpoints. Returns None if valid, JSONResponse if invalid."""
    token = request.cookies.get("admin_token")
    if not token:
        return JSONResponse({"detail": "Unauthorized: admin token missing"}, status_code=401)

    r = await get_redis()
    session_exists = await r.get(f"admin_session:{token}")
    if not session_exists:
        return JSONResponse({"detail": "Unauthorized: invalid or expired session"}, status_code=401)

    return None


async def require_admin(request: Request) -> RedirectResponse | None:
    """Dependency for admin page routes. Returns redirect if invalid, None if valid."""
    token = request.cookies.get("admin_token")
    if not token:
        return RedirectResponse(url="/admin/login", status_code=303)
    try:
        r = await get_redis()
        valid = await r.get(f"admin_session:{token}")
        if valid:
            return None
    except Exception as e:
        logger.error(f"Admin auth Redis error: {e}")
    return RedirectResponse(url="/admin/login", status_code=303)


# ── Login ──────────────────────────────────────────────────

@router.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return request.app.state.templates.TemplateResponse("admin/login.html", {
        "request": request,
    })


@router.post("/admin/login")
async def login_submit(request: Request, password: str = Form(...)):
    if _verify_password(password):
        token = secrets.token_urlsafe(32)
        r = await get_redis()
        await r.setex(f"admin_session:{token}", 86400, "1")  # 24h TTL
        response = RedirectResponse(url="/admin/dashboard", status_code=303)
        response.set_cookie("admin_token", token, httponly=True, max_age=86400)
        return response
    return request.app.state.templates.TemplateResponse("admin/login.html", {
        "request": request,
        "error": "Invalid password",
    })


@router.get("/admin/logout")
async def admin_logout(request: Request):
    token = request.cookies.get("admin_token")
    if token:
        r = await get_redis()
        await r.delete(f"admin_session:{token}")
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("admin_token")
    return response


# ── Dashboard ──────────────────────────────────────────────

async def _get_dashboard_stats(db: AsyncSession) -> dict:
    """Shared stats query for dashboard page and API."""
    total = await db.execute(select(func.count(Participant.id)))
    finished = await db.execute(
        select(func.count(Participant.id)).where(Participant.is_finished == True)
    )
    active = await db.execute(
        select(func.count(Participant.id)).where(Participant.is_finished == False)
    )
    in_chat = await db.execute(
        select(func.count(Participant.id)).where(
            Participant.current_step.in_([Step.chat_r1, Step.chat_r2])
        )
    )

    condition_data = {}
    for task_type in ["emotionTask", "functionTask"]:
        for partnership in ["HHC", "HMC"]:
            for label in ["chatbot", "human"]:
                key = f"{task_type}_{partnership}_{label}"
                result = await db.execute(
                    select(func.count(Participant.id)).where(
                        Participant.task_type == task_type,
                        Participant.partnership == partnership,
                        Participant.partner_label == label,
                    )
                )
                condition_data[key] = result.scalar() or 0

    # Step distribution (active participants only)
    step_data = {}
    for step in Step:
        if step == Step.payment:
            continue  # skip payment, tracked via is_finished
        result = await db.execute(
            select(func.count(Participant.id)).where(
                Participant.current_step == step,
                Participant.is_finished == False,
            )
        )
        count = result.scalar() or 0
        if count > 0:
            step_data[step.value] = count

    # Active chat rooms — auto-cleanup stale rooms exceeding MAX_DURATION
    active_rooms_result = await db.execute(
        select(ChatRoom)
        .where(ChatRoom.is_active == True)
        .options(selectinload(ChatRoom.participant))
        .order_by(ChatRoom.started_at.desc())
    )
    # Store in list to avoid double-consumption of async result cursor
    all_active_rooms = list(active_rooms_result.scalars().all())

    # BUG-D7 FIX: Auto-deactivate rooms that exceeded MAX_DURATION.
    # This handles abandoned sessions where user closed browser without ending chat.
    max_duration = settings.DEMO_MAX_DURATION if settings.DEMO_MODE else settings.MAX_DURATION
    now = datetime.now(timezone.utc)
    stale_count = 0
    for room in all_active_rooms:
        if room.started_at and (now - room.started_at).total_seconds() > max_duration + 300:
            # 5-minute grace period beyond max_duration
            room.is_active = False
            room.ended_at = now
            room.duration_seconds = (now - room.started_at).total_seconds()
            stale_count += 1
    if stale_count > 0:
        await db.commit()
        logger.info(f"Auto-deactivated {stale_count} stale chat rooms (exceeded max_duration)")
        # Re-query after cleanup
        active_rooms_result = await db.execute(
            select(ChatRoom)
            .where(ChatRoom.is_active == True)
            .options(selectinload(ChatRoom.participant))
            .order_by(ChatRoom.started_at.desc())
        )
        all_active_rooms = list(active_rooms_result.scalars().all())
    active_rooms = []
    for room in all_active_rooms:
        p = room.participant
        active_rooms.append({
            "room_uuid": str(room.id),
            "room_id": room.room_id or "",
            "room_type": room.room_type.value,
            "round_number": room.round_number,
            "turn_count": room.turn_count,
            "started_at": room.started_at.isoformat() if room.started_at else None,
            "participant": {
                "id": str(p.id),
                "display_id": p.display_id,
                "nickname": p.nickname or "",
                "avatar": p.avatar or "",
                "task_type": p.task_type.value,
            },
        })

    # Active participants with progress info
    step_order = list(Step)
    active_participants_raw = await db.execute(
        select(Participant)
        .where(Participant.is_finished == False)
        .order_by(Participant.created_at.desc())
        .limit(50)
    )
    active_participants = []
    for p in active_participants_raw.scalars().all():
        idx = step_order.index(p.current_step)
        progress = round((idx / (len(step_order) - 1)) * 100)
        active_participants.append({
            "id": str(p.id),
            "display_id": p.display_id,
            "nickname": p.nickname or "",
            "current_step": p.current_step.value,
            "progress": progress,
            "is_timeout": p.is_timeout,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })

    return {
        "total": total.scalar() or 0,
        "finished": finished.scalar() or 0,
        "active": active.scalar() or 0,
        "in_chat": in_chat.scalar() or 0,
        "conditions": condition_data,
        "steps": step_data,
        "active_rooms": active_rooms,
        "active_participants": active_participants,
        "stuck_participants": await detect_stuck_participants(db),
    }


@router.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db), _auth=Depends(require_admin)):
    if _auth:
        return _auth
    stats = await _get_dashboard_stats(db)
    return request.app.state.templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "nav": "dashboard",
        **stats,
    })


@router.get("/api/admin/stats")
async def dashboard_stats_api(request: Request, db: AsyncSession = Depends(get_db)):
    """API endpoint for real-time dashboard polling."""
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    stats = await _get_dashboard_stats(db)
    return JSONResponse(stats)


# ── Participants List ──────────────────────────────────────

@router.get("/admin/participants", response_class=HTMLResponse)
async def participants(request: Request, db: AsyncSession = Depends(get_db), _auth=Depends(require_admin)):
    if _auth:
        return _auth
    result = await db.execute(
        select(Participant).order_by(Participant.created_at.desc())
    )
    participants = result.scalars().all()
    return request.app.state.templates.TemplateResponse("admin/participants.html", {
        "request": request,
        "nav": "participants",
        "participants": participants,
    })


# ── Config Editor ──────────────────────────────────────────


# ── Participant Detail ─────────────────────────────────────

@router.get("/admin/participant/{display_id}", response_class=HTMLResponse)
async def participant_detail(display_id: str, request: Request, db: AsyncSession = Depends(get_db), _auth=Depends(require_admin)):
    if _auth:
        return _auth
    result = await db.execute(
        select(Participant).where(Participant.display_id == display_id)
    )
    participant = result.scalar_one_or_none()
    if not participant:
        return request.app.state.templates.TemplateResponse("404.html", {"request": request})

    # Chat rooms + messages
    rooms_data = []
    for room in participant.chat_rooms:
        messages = [
            {"sender_role": m.sender_role.value, "text": m.text, "turn_number": m.turn_number, "created_at": m.created_at.isoformat() if m.created_at else None}
            for m in room.messages
        ]
        rooms_data.append({
            "id": str(room.id),
            "room_type": room.room_type.value,
            "round_number": room.round_number,
            "turn_count": room.turn_count,
            "duration_seconds": room.duration_seconds,
            "started_at": room.started_at.isoformat() if room.started_at else None,
            "ended_at": room.ended_at.isoformat() if room.ended_at else None,
            "is_active": room.is_active,
            "messages": messages,
        })

    # Step duration history
    step_events = await db.execute(
        select(ExperimentSession).where(
            ExperimentSession.participant_id == participant.id,
            ExperimentSession.event == "step_duration",
        ).order_by(ExperimentSession.created_at)
    )
    step_durations = []
    for se in step_events.scalars().all():
        meta = se.metadata_json or {}
        step_durations.append({
            "from_step": meta.get("from_step", ""),
            "to_step": meta.get("to_step", ""),
            "duration_seconds": meta.get("duration_seconds", 0),
            "is_over_limit": meta.get("is_over_limit", False),
            "time_limit": meta.get("time_limit"),
        })

    # Recent events for this participant
    recent_events = await db.execute(
        select(ExperimentSession).where(
            ExperimentSession.participant_id == participant.id,
        ).order_by(ExperimentSession.created_at.desc()).limit(20)
    )
    events_data = []
    for es in recent_events.scalars().all():
        events_data.append({
            "event": es.event,
            "step": es.step,
            "metadata": es.metadata_json,
            "created_at": es.created_at.isoformat() if es.created_at else None,
        })

    # Survey response
    survey_data = None
    if participant.survey_response:
        sr = participant.survey_response
        survey_data = {col: getattr(sr, col) for col in sr.__table__.columns.keys() if col not in ('id', 'participant_id', 'created_at')}

    resume_url = f"/resume/{participant.resume_token}" if participant.resume_token else None

    # Progress info
    step_order = list(Step)
    current_idx = step_order.index(participant.current_step)
    progress = round((current_idx / (len(step_order) - 1)) * 100)
    steps_info = [{"step": s.value, "label": s.value.replace("_", " ").title(), "index": i} for i, s in enumerate(step_order)]

    return request.app.state.templates.TemplateResponse("admin/participant_detail.html", {
        "request": request,
        "nav": "participants",
        "p": participant,
        "progress": progress,
        "steps_info": steps_info,
        "current_step_index": current_idx,
        "rooms": rooms_data,
        "step_durations": step_durations,
        "events": events_data,
        "survey": survey_data,
        "resume_url": resume_url,
    })


# ── Event Feed API ─────────────────────────────────────────

@router.get("/api/admin/events")
async def event_feed(
    request: Request,
    db: AsyncSession = Depends(get_db),
    since: str | None = None,
    limit: int = 50,
):
    """Return recent events for the real-time event feed."""
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error

    query = (
        select(ExperimentSession)
        .order_by(ExperimentSession.created_at.desc())
        .limit(limit)
    )
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.where(ExperimentSession.created_at > since_dt)
        except ValueError:
            pass

    result = await db.execute(query)
    events = []
    for es in result.scalars().all():
        events.append({
            "id": str(es.id),
            "event": es.event,
            "step": es.step,
            "metadata": es.metadata_json,
            "participant_id": str(es.participant_id),
            "created_at": es.created_at.isoformat(),
        })

    return JSONResponse({"events": events})


# ── LLM Stats API ──────────────────────────────────────────

@router.get("/api/admin/llm-stats")
async def llm_stats(request: Request, db: AsyncSession = Depends(get_db)):
    """Return aggregate LLM call statistics."""
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error

    all_llm_calls = await db.execute(
        select(ExperimentSession).where(
            ExperimentSession.event == "llm_call"
        ).order_by(ExperimentSession.created_at.desc()).limit(20)
    )
    all_calls = all_llm_calls.scalars().all()

    total = 0
    success = 0
    recent_calls = []
    for es in all_calls:
        total += 1
        meta = es.metadata_json or {}
        is_success = meta.get("success", False)
        if is_success:
            success += 1
        recent_calls.append({
            "success": is_success,
            "fallback": meta.get("fallback", False),
            "task_type": meta.get("task_type", ""),
            "partner_label": meta.get("partner_label", ""),
            "turn_number": meta.get("turn_number", ""),
            "created_at": es.created_at.isoformat(),
            "participant_id": str(es.participant_id),
        })



    return JSONResponse({
        "total_calls": total,
        "successful_calls": success,
        "failed_calls": total - success,
        "error_rate": round(((total - success) / total * 100), 1) if total > 0 else 0,
        "recent_calls": recent_calls,
    })








# ── Chat Monitor API ───────────────────────────────────────

@router.get("/api/admin/chat/{room_uuid}")
async def get_chat_messages(room_uuid: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Get all messages for a chat room (for admin monitoring)."""
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error

    try:
        rid = uuid.UUID(room_uuid)
    except ValueError:
        return JSONResponse({"detail": "Invalid room UUID"}, status_code=400)

    result = await db.execute(
        select(ChatRoom).options(selectinload(ChatRoom.participant)).where(ChatRoom.id == rid)
    )
    room = result.scalar_one_or_none()
    if not room:
        return JSONResponse({"detail": "Room not found"}, status_code=404)

    messages = []
    for msg in room.messages:
        messages.append({
            "sender_role": msg.sender_role.value,
            "text": msg.text,
            "turn_number": msg.turn_number,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        })

    return JSONResponse({
        "room_id": room.room_id,
        "room_type": room.room_type.value,
        "round_number": room.round_number,
        "is_active": room.is_active,
        "turn_count": room.turn_count,
        "participant": {
            "display_id": room.participant.display_id,
            "nickname": room.participant.nickname or "",
        },
        "messages": messages,
    })


# ── Config Editor ──────────────────────────────────────────

CONFIG_KEYS = {
    "CHARACTER_PROMPT_A": "Emotion task + MyBot (AI) prompt",
    "CHARACTER_PROMPT_Afake": "Emotion task + Tommy (fake human) prompt",
    "CHARACTER_PROMPT_B": "Function task + MyBot (AI) prompt",
    "CHARACTER_PROMPT_Bfake": "Function task + Tommy (fake human) prompt",
    "default_model": "LLM model name (e.g., gpt-4o-mini)",
    "min_turns": "Minimum chat turns before Next button enabled",
    "max_turns": "Maximum chat turns (auto-end)",
    "max_duration": "Chat max duration in seconds",
}


@router.get("/admin/config", response_class=HTMLResponse)
async def config_page(request: Request, db: AsyncSession = Depends(get_db), _auth=Depends(require_admin)):
    if _auth:
        return _auth
    result = await db.execute(select(ExperimentConfig).order_by(ExperimentConfig.key))
    configs = result.scalars().all()
    config_dict = {c.key: c for c in configs}
    return request.app.state.templates.TemplateResponse("admin/config.html", {
        "request": request,
        "nav": "config",
        "config_dict": config_dict,
        "config_keys": CONFIG_KEYS,
    })


@router.post("/admin/config")
async def config_update(request: Request, db: AsyncSession = Depends(get_db), _auth=Depends(require_admin)):
    if _auth:
        return _auth
    form = await request.form()
    for key in CONFIG_KEYS:
        value = form.get(key, "")
        result = await db.execute(
            select(ExperimentConfig).where(ExperimentConfig.key == key)
        )
        config = result.scalar_one_or_none()
        if config:
            config.value = str(value)
        elif value:
            config = ExperimentConfig(key=key, value=str(value), description=CONFIG_KEYS[key])
            db.add(config)
    await db.commit()
    # Invalidate LLM config cache so next chat picks up new values
    from services.llm import invalidate_config_cache
    invalidate_config_cache()
    return RedirectResponse(url="/admin/config", status_code=303)


# ── Data Export ────────────────────────────────────────────

@router.get("/admin/export", response_class=HTMLResponse)
async def export_page(request: Request, _auth=Depends(require_admin)):
    if _auth:
        return _auth
    return request.app.state.templates.TemplateResponse("admin/data_export.html", {
        "request": request,
        "nav": "export",
    })


@router.get("/admin/export/{format_type}")
async def export_data(request: Request, format_type: str, include_test: bool = False, db: AsyncSession = Depends(get_db)):
    # SECURITY: Require admin session for data export
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error

    if format_type == "participants":
        csv_data = await export_participant_table(db, include_test=include_test)
        filename = "participants.csv"
    elif format_type == "chat":
        csv_data = await export_chat_messages(db, include_test=include_test)
        filename = "chat_messages.csv"
    else:
        return JSONResponse({"detail": "Invalid format"}, status_code=400)

    return JSONResponse(
        content={"csv": csv_data, "filename": filename},
        media_type="application/json",
    )


# ── Test Tools ──────────────────────────────────────────────

@router.get("/admin/test-tools", response_class=HTMLResponse)
async def test_tools_page(request: Request, _auth=Depends(require_admin)):
    if _auth:
        return _auth
    return request.app.state.templates.TemplateResponse("admin/test_tools.html", {
        "request": request,
        "nav": "test-tools",
        "demo_mode": settings.DEMO_MODE,
    })


async def _generate_display_id(db: AsyncSession) -> str:
    """Generate unique display_id like P-0001."""
    # Get the participant with highest display_id to handle deletions
    result = await db.execute(
        select(Participant.display_id)
        .where(Participant.display_id.like("P-%"))
        .order_by(Participant.display_id.desc())
        .limit(1)
    )
    last_display_id = result.scalar()
    if last_display_id:
        # Extract number from P-XXXX format
        last_num = int(last_display_id.split('-')[1])
        return f"P-{last_num + 1:04d}"
    return "P-0001"


@router.post("/api/admin/test/participant")
async def create_test_participant(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a test participant with specified conditions and start step."""
    # Verify admin session
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    form = await request.form()
    task_type = form.get("task_type", "emotionTask")
    partnership = form.get("partnership", "HMC")
    partner_label = form.get("partner_label", "chatbot")
    nickname = form.get("nickname", "TestUser")
    avatar = form.get("avatar", "lion.png")
    start_step = form.get("start_step", "instructions_r1")

    # Validate nickname and avatar
    if not nickname or len(nickname) > 50:
        return JSONResponse({"detail": "Nickname must be 1-50 characters"}, status_code=400)
    if not avatar or len(avatar) > 100:
        return JSONResponse({"detail": "Avatar must be 1-100 characters"}, status_code=400)

    # Parse enums
    try:
        tt = TaskType(task_type)
        ps = Partnership(partnership)
        pl = PartnerLabel(partner_label)
        step = Step(start_step)
    except ValueError as e:
        return JSONResponse({"detail": f"Invalid value: {e}"}, status_code=400)

    display_id = await _generate_display_id(db)
    participant = Participant(
        id=uuid.uuid4(),
        display_id=display_id,
        task_type=tt,
        partnership=ps,
        partner_label=pl,
        current_step=step,
        is_test=True,
        avatar=avatar,
        nickname=nickname,
        priming_text="(test participant - no priming)",
        resume_token=secrets.token_urlsafe(48),
    )

    # Auto-fill prerequisites based on start_step
    step_order = list(Step)
    step_index = step_order.index(step)

    # If past consent, mark as consented (no explicit consented field, step > consent implies consent)
    # If past welcome, set avatar and nickname
    if step_index >= step_order.index(Step.priming):
        participant.priming_text = "(test participant - no priming)"
    if step_index >= step_order.index(Step.welcome):
        pass  # Already set above
    # Set round based on step
    if step_index >= step_order.index(Step.instructions_r2):
        participant.current_round = 2
    else:
        participant.current_round = 1

    db.add(participant)
    await db.commit()
    await db.refresh(participant)

    # BUG-04 FIX: Auto-create HMC ChatRoom if starting at chat step with HMC partnership
    # This matches the behavior of set_test_step (BUG-02 fix ensures _redirect finds the room)
    if step in (Step.chat_r1, Step.chat_r2) and ps == Partnership.HMC:
        existing = await db.execute(
            select(ChatRoom).where(
                ChatRoom.participant_id == participant.id,
                ChatRoom.round_number == participant.current_round,
                ChatRoom.is_active == True,
            )
        )
        if not existing.scalar_one_or_none():
            room = ChatRoom(
                participant_id=participant.id,
                room_type=RoomType.HMC,
                round_number=participant.current_round,
                room_id=str(uuid.uuid4())[:8],
                # BUG-D9: started_at set when WebSocket connects
            )
            db.add(room)
            await db.commit()
            await db.refresh(room)

    url = f"/experiment/{participant.id}"
    return JSONResponse({
        "url": url,
        "display_id": display_id,
        "participant_id": str(participant.id),
        "resume_url": f"/resume/{participant.resume_token}" if participant.resume_token else None,
    })


@router.post("/api/admin/test/set-step")
async def set_test_step(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Set a participant's current step (for testing)."""
    # Verify admin session
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    form = await request.form()
    pid = form.get("participant_id", "")
    step_str = form.get("step", "instructions_r1")

    try:
        participant_id = uuid.UUID(pid)
        step = Step(step_str)
    except (ValueError, Exception) as e:
        return JSONResponse({"detail": f"Invalid input: {e}"}, status_code=400)

    participant = await db.get(Participant, participant_id)
    if not participant:
        return JSONResponse({"detail": "Participant not found"}, status_code=404)

    step_order = list(Step)
    new_step_index = step_order.index(step)
    old_step_index = step_order.index(participant.current_step)  # capture BEFORE update

    participant.current_step = step

    # Update round number
    if new_step_index >= step_order.index(Step.instructions_r2):
        participant.current_round = 2
    elif new_step_index < step_order.index(Step.instructions_r2):
        participant.current_round = 1

    # If moving backward from chat step, deactivate any active chat rooms for future rounds
    if new_step_index < old_step_index:
        for round_num in (1, 2):
            # If moving to round 1, deactivate round 2 rooms; if moving to pre-chat, deactivate all
            if new_step_index < step_order.index(Step.chat_r1) or round_num >= participant.current_round:
                rooms = await db.execute(
                    select(ChatRoom).where(
                        ChatRoom.participant_id == participant.id,
                        ChatRoom.round_number == round_num,
                        ChatRoom.is_active == True,
                    )
                )
                for room in rooms.scalars().all():
                    room.is_active = False
                    room.ended_at = datetime.now(timezone.utc)

    # If jumping to a chat step and HMC, auto-create HMC ChatRoom
    if step in (Step.chat_r1, Step.chat_r2) and participant.partnership == Partnership.HMC:
        from datetime import datetime, timezone
        existing = await db.execute(
            select(ChatRoom).where(
                ChatRoom.participant_id == participant.id,
                ChatRoom.round_number == participant.current_round,
                ChatRoom.is_active == True,
            )
        )
        if not existing.scalar_one_or_none():
            room = ChatRoom(
                participant_id=participant.id,
                room_type=RoomType.HMC,
                round_number=participant.current_round,
                room_id=str(uuid.uuid4())[:8],
                # BUG-D9: started_at set when WebSocket connects
            )
            db.add(room)

    await db.commit()
    return JSONResponse({"detail": f"Step set to {step.value}"})


@router.get("/api/admin/test/hhc-queues")
async def get_hhc_queues(request: Request):
    """Return all HHC matchmaking queue status."""
    # Verify admin session
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    from services.matchmaking import get_all_queue_members
    queues = await get_all_queue_members()
    return JSONResponse({"queues": queues})


@router.post("/api/admin/test/clear-queue")
async def clear_hhc_queue(request: Request):
    """Clear a specific HHC matchmaking queue."""
    # Verify admin session
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    form = await request.form()
    queue_name = form.get("queue_name", "")
    if not queue_name:
        return JSONResponse({"detail": "queue_name required"}, status_code=400)

    from services.matchmaking import clear_queue
    count = await clear_queue(queue_name)
    return JSONResponse({"detail": f"Cleared {count} participants from {queue_name}"})


@router.post("/api/admin/test/force-match")
async def force_match(request: Request, db: AsyncSession = Depends(get_db)):
    """Force-match two participants for HHC chat."""
    # Verify admin session
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    form = await request.form()
    p1_id = form.get("participant1_id", "")
    p2_id = form.get("participant2_id", "")

    # Validate round_number
    try:
        round_number = int(form.get("round_number", "1"))
        if round_number not in (1, 2):
            return JSONResponse({"detail": "round_number must be 1 or 2"}, status_code=400)
    except ValueError:
        return JSONResponse({"detail": "Invalid round_number"}, status_code=400)

    try:
        uuid1 = uuid.UUID(p1_id)
        uuid2 = uuid.UUID(p2_id)
    except ValueError:
        return JSONResponse({"detail": "Invalid participant IDs"}, status_code=400)

    p1 = await db.get(Participant, uuid1)
    p2 = await db.get(Participant, uuid2)

    if not p1 or not p2:
        return JSONResponse({"detail": "Participant(s) not found"}, status_code=404)
    if uuid1 == uuid2:
        return JSONResponse({"detail": "Cannot match participant with themselves"}, status_code=400)
    if p1.task_type != p2.task_type:
        return JSONResponse({"detail": "Participants must have same task_type"}, status_code=400)
    if p1.is_finished or p2.is_finished:
        return JSONResponse({"detail": "Participant(s) already finished"}, status_code=400)

    # Dequeue both if in queue
    task_type = p1.task_type.value
    await dequeue_match(p1_id, round_number, task_type)
    await dequeue_match(p2_id, round_number, task_type)

    # Create HHC ChatRooms for both participants
    room_id = f"hhc-{round_number}-{p1_id[:8]}-{p2_id[:8]}"
    room1 = ChatRoom(
        participant_id=uuid1,
        room_type=RoomType.HHC,
        round_number=round_number,
        room_id=room_id,
        # BUG-D9: started_at set when WebSocket connects
    )
    room2 = ChatRoom(
        participant_id=uuid2,
        room_type=RoomType.HHC,
        round_number=round_number,
        room_id=room_id,
        # BUG-D9: started_at set when WebSocket connects
    )
    db.add(room1)
    db.add(room2)

    # Set partner references
    p1.partner_id = uuid2
    p2.partner_id = uuid1
    p1.current_step = Step.chat_r1 if round_number == 1 else Step.chat_r2
    p2.current_step = Step.chat_r1 if round_number == 1 else Step.chat_r2
    p1.current_round = round_number
    p2.current_round = round_number
    # Clear hhc_fallback flag if previously set
    p1.hhc_fallback = False
    p2.hhc_fallback = False

    await db.commit()
    await db.refresh(room1)
    await db.refresh(room2)

    # Set match result notifications for BOTH participants
    await set_match_result(p1_id, str(room1.id), room_id)
    await set_match_result(p2_id, str(room2.id), room_id)

    return JSONResponse({
        "room_id": room_id,
        "participant1": {
            "id": str(uuid1),
            "display_id": p1.display_id,
            "room_url": f"/chat?room={room1.id}",
            "entry_url": f"/experiment/{uuid1}",
        },
        "participant2": {
            "id": str(uuid2),
            "display_id": p2.display_id,
            "room_url": f"/chat?room={room2.id}",
            "entry_url": f"/experiment/{uuid2}",
        },
    })


@router.post("/api/admin/test/create-pair")
async def create_test_pair(request: Request, db: AsyncSession = Depends(get_db)):
    """Create two HHC test participants and force-match them (one-click)."""
    # Verify admin session
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    form = await request.form()
    task_type = form.get("task_type", "emotionTask")

    # Validate round_number
    try:
        round_number = int(form.get("round_number", "1"))
        if round_number not in (1, 2):
            return JSONResponse({"detail": "round_number must be 1 or 2"}, status_code=400)
    except ValueError:
        return JSONResponse({"detail": "Invalid round_number"}, status_code=400)

    nickname1 = form.get("nickname1", "Alice")
    nickname2 = form.get("nickname2", "Bob")

    try:
        tt = TaskType(task_type)
    except ValueError:
        return JSONResponse({"detail": "Invalid task_type"}, status_code=400)

    chat_step = Step.chat_r1 if round_number == 1 else Step.chat_r2

    # Create two test participants with unique display_ids
    id1 = uuid.uuid4()
    id2 = uuid.uuid4()
    display_id1 = await _generate_display_id(db)

    p1 = Participant(
        id=id1,
        display_id=display_id1,
        task_type=tt,
        partnership=Partnership.HHC,
        partner_label=PartnerLabel.chatbot,
        current_step=chat_step,
        current_round=round_number,
        is_test=True,
        avatar="lion.png",
        nickname=nickname1,
        priming_text="(test participant)",
        resume_token=secrets.token_urlsafe(48),
    )
    db.add(p1)
    # Flush to make p1 visible to the database for the next _generate_display_id call
    await db.flush()

    # Now generate display_id2 - it will see p1 and use the next number
    display_id2 = await _generate_display_id(db)

    p2 = Participant(
        id=id2,
        display_id=display_id2,
        task_type=tt,
        partnership=Partnership.HHC,
        partner_label=PartnerLabel.human,
        current_step=chat_step,
        current_round=round_number,
        is_test=True,
        avatar="fox.png",
        nickname=nickname2,
        priming_text="(test participant)",
        resume_token=secrets.token_urlsafe(48),
    )
    db.add(p2)

    # Create HHC rooms
    room_id = f"hhc-{round_number}-{str(id1)[:8]}-{str(id2)[:8]}"
    room1 = ChatRoom(
        participant_id=id1,
        room_type=RoomType.HHC,
        round_number=round_number,
        room_id=room_id,
        # BUG-D9: started_at set when WebSocket connects
    )
    room2 = ChatRoom(
        participant_id=id2,
        room_type=RoomType.HHC,
        round_number=round_number,
        room_id=room_id,
        # BUG-D9: started_at set when WebSocket connects
    )
    db.add(room1)
    db.add(room2)

    # Set partner references
    p1.partner_id = id2
    p2.partner_id = id1

    await db.commit()
    await db.refresh(room1)
    await db.refresh(room2)

    # Set match result notifications for BOTH participants
    await set_match_result(str(id1), str(room1.id), room_id)
    await set_match_result(str(id2), str(room2.id), room_id)

    return JSONResponse({
        "room_id": room_id,
        "participant1": {
            "id": str(id1),
            "display_id": display_id1,
            "entry_url": f"/experiment/{id1}",
            "room_url": f"/chat?room={room1.id}",
        },
        "participant2": {
            "id": str(id2),
            "display_id": display_id2,
            "entry_url": f"/experiment/{id2}",
            "room_url": f"/chat?room={room2.id}",
        },
    })


@router.post("/api/admin/test/delete-participant")
async def delete_test_participant(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single test participant and associated data."""
    # Verify admin session
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    form = await request.form()
    pid = form.get("participant_id", "")

    try:
        participant_id = uuid.UUID(pid)
    except ValueError:
        return JSONResponse({"detail": "Invalid UUID"}, status_code=400)

    participant = await db.get(Participant, participant_id)
    if not participant:
        return JSONResponse({"detail": "Participant not found"}, status_code=404)

    if not participant.is_test:
        return JSONResponse({"detail": "Can only delete test participants (is_test=True)"}, status_code=400)

    # Clear partner reference if HHC
    if participant.partner_id:
        partner = await db.get(Participant, participant.partner_id)
        if partner:
            partner.partner_id = None

    # Dequeue from all HHC matchmaking queues
    for round_num in (1, 2):
        await dequeue_match(str(participant_id), round_num, participant.task_type.value)

    # Delete associated chat rooms and messages
    result = await db.execute(
        select(ChatRoom).where(ChatRoom.participant_id == participant_id)
    )
    for room in result.scalars().all():
        await db.delete(room)

    # Delete survey response if exists
    from models.survey import SurveyResponse
    sr_result = await db.execute(
        select(SurveyResponse).where(SurveyResponse.participant_id == participant_id)
    )
    for sr in sr_result.scalars().all():
        await db.delete(sr)

    # Delete session logs
    from models.experiment import ExperimentSession
    sess_result = await db.execute(
        select(ExperimentSession).where(ExperimentSession.participant_id == participant_id)
    )
    for s in sess_result.scalars().all():
        await db.delete(s)

    await db.delete(participant)
    await db.commit()

    return JSONResponse({"detail": f"Deleted test participant {participant.display_id}"})


@router.post("/api/admin/test/cleanup-all")
async def cleanup_all_test_data(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete all test participants and their associated data."""
    # Verify admin session
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    result = await db.execute(
        select(Participant).where(Participant.is_test == True)
    )
    test_participants = result.scalars().all()
    count = len(test_participants)

    if count == 0:
        return JSONResponse({"detail": "No test participants to delete"})

    for p in test_participants:
        # Delete chat rooms (cascade should handle messages)
        rooms = await db.execute(
            select(ChatRoom).where(ChatRoom.participant_id == p.id)
        )
        for room in rooms.scalars().all():
            await db.delete(room)

        # Delete survey response
        from models.survey import SurveyResponse
        sr = await db.execute(
            select(SurveyResponse).where(SurveyResponse.participant_id == p.id)
        )
        for s in sr.scalars().all():
            await db.delete(s)

        # Delete session logs
        from models.experiment import ExperimentSession
        sessions = await db.execute(
            select(ExperimentSession).where(ExperimentSession.participant_id == p.id)
        )
        for s in sessions.scalars().all():
            await db.delete(s)

        await db.delete(p)

    await db.commit()
    return JSONResponse({"detail": f"Deleted {count} test participant(s)"})


@router.get("/api/admin/test/count")
async def test_data_count(request: Request, db: AsyncSession = Depends(get_db)):
    """Return count of test participants for display on the Test Tools page."""
    # Verify admin session
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    result = await db.execute(
        select(func.count(Participant.id)).where(Participant.is_test == True)
    )
    count = result.scalar() or 0
    return JSONResponse({"count": count})


# ── New Test Tool Endpoints ─────────────────────────────────

@router.get("/api/admin/test/participants")
async def list_test_participants(request: Request, db: AsyncSession = Depends(get_db)):
    """Return all test participants for the test tools dashboard."""
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    result = await db.execute(
        select(Participant)
        .where(Participant.is_test == True)
        .order_by(Participant.created_at.desc())
    )
    participants = result.scalars().all()
    return JSONResponse({
        "participants": [
            {
                "id": str(p.id),
                "display_id": p.display_id,
                "nickname": p.nickname or "",
                "avatar": p.avatar or "",
                "task_type": p.task_type.value,
                "partnership": p.partnership.value,
                "partner_label": p.partner_label.value,
                "current_step": p.current_step.value,
                "current_round": p.current_round,
                "is_finished": p.is_finished,
                "partner_id": str(p.partner_id) if p.partner_id else None,
                "resume_url": f"/resume/{p.resume_token}" if p.resume_token else None,
            }
            for p in participants
        ]
    })


@router.post("/api/admin/test/quick-create")
async def quick_create_test_participant(
    request: Request, db: AsyncSession = Depends(get_db),
):
    """Create a test participant at instructions_r1 with default HMC conditions."""
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error

    display_id = await _generate_display_id(db)
    participant = Participant(
        id=uuid.uuid4(),
        display_id=display_id,
        task_type=TaskType.emotionTask,
        partnership=Partnership.HMC,
        partner_label=PartnerLabel.chatbot,
        current_step=Step.instructions_r1,
        is_test=True,
        avatar="lion.png",
        nickname="QuickTest",
        priming_text="(test participant - no priming)",
        resume_token=secrets.token_urlsafe(48),
    )
    db.add(participant)
    await db.commit()
    await db.refresh(participant)

    return JSONResponse({
        "id": str(participant.id),
        "display_id": display_id,
        "url": f"/experiment/{participant.id}",
        "resume_url": f"/resume/{participant.resume_token}" if participant.resume_token else None,
        "current_step": "instructions_r1",
    })


@router.post("/api/admin/test/matchmaking-test")
async def matchmaking_test_pair(
    request: Request, db: AsyncSession = Depends(get_db),
):
    """Create two HHC participants at instructions_r1 for full flow testing.

    Opens both at instructions so the tester can walk through
    instructions -> waiting room -> real matchmaking.
    """
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error

    form = await request.form()
    task_type_str = form.get("task_type", "emotionTask")
    nickname1 = form.get("nickname1", "TestAlice")
    nickname2 = form.get("nickname2", "TestBob")

    try:
        tt = TaskType(task_type_str)
    except ValueError:
        return JSONResponse({"detail": "Invalid task_type"}, status_code=400)

    id1 = uuid.uuid4()
    display_id1 = await _generate_display_id(db)
    p1 = Participant(
        id=id1,
        display_id=display_id1,
        task_type=tt,
        partnership=Partnership.HHC,
        partner_label=PartnerLabel.chatbot,
        current_step=Step.instructions_r1,
        is_test=True,
        avatar="lion.png",
        nickname=nickname1,
        priming_text="(test participant)",
        resume_token=secrets.token_urlsafe(48),
    )
    db.add(p1)
    await db.flush()

    id2 = uuid.uuid4()
    display_id2 = await _generate_display_id(db)
    p2 = Participant(
        id=id2,
        display_id=display_id2,
        task_type=tt,
        partnership=Partnership.HHC,
        partner_label=PartnerLabel.human,
        current_step=Step.instructions_r1,
        is_test=True,
        avatar="fox.png",
        nickname=nickname2,
        priming_text="(test participant)",
        resume_token=secrets.token_urlsafe(48),
    )
    db.add(p2)
    await db.commit()
    await db.refresh(p1)
    await db.refresh(p2)

    return JSONResponse({
        "participant1": {
            "id": str(id1),
            "display_id": display_id1,
            "nickname": nickname1,
            "url": f"/experiment/{id1}",
        },
        "participant2": {
            "id": str(id2),
            "display_id": display_id2,
            "nickname": nickname2,
            "url": f"/experiment/{id2}",
        },
    })


@router.post("/api/admin/test/next-step")
async def next_test_step(
    request: Request, db: AsyncSession = Depends(get_db),
):
    """Advance a test participant to the next step in sequence."""
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    form = await request.form()
    pid = form.get("participant_id", "")

    try:
        participant_id = uuid.UUID(pid)
    except ValueError:
        return JSONResponse({"detail": "Invalid UUID"}, status_code=400)

    participant = await db.get(Participant, participant_id)
    if not participant:
        return JSONResponse({"detail": "Participant not found"}, status_code=404)

    step_order = list(Step)
    current_index = step_order.index(participant.current_step)
    if current_index >= len(step_order) - 1:
        return JSONResponse({"detail": "Already at last step"}, status_code=400)

    next_step = step_order[current_index + 1]
    participant.current_step = next_step

    # Update round number
    if next_step == Step.instructions_r2:
        participant.current_round = 2

    # Auto-create HMC ChatRoom when advancing to chat step
    if next_step in (Step.chat_r1, Step.chat_r2) and participant.partnership == Partnership.HMC:
        existing = await db.execute(
            select(ChatRoom).where(
                ChatRoom.participant_id == participant.id,
                ChatRoom.round_number == participant.current_round,
                ChatRoom.is_active == True,
            )
        )
        if not existing.scalar_one_or_none():
            room = ChatRoom(
                participant_id=participant.id,
                room_type=RoomType.HMC,
                round_number=participant.current_round,
                room_id=str(uuid.uuid4())[:8],
                # BUG-D9: started_at set when WebSocket connects
            )
            db.add(room)

    await db.commit()
    return JSONResponse({
        "detail": f"Advanced to {next_step.value}",
        "current_step": next_step.value,
    })


@router.get("/api/admin/test/participant-options")
async def test_participant_options(request: Request, db: AsyncSession = Depends(get_db)):
    """Return test participant options for dropdown selectors."""
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    result = await db.execute(
        select(Participant)
        .where(Participant.is_test == True)
        .order_by(Participant.created_at.desc())
    )
    participants = result.scalars().all()
    return JSONResponse({
        "participants": [
            {
                "id": str(p.id),
                "display_id": p.display_id,
                "nickname": p.nickname or "",
                "current_step": p.current_step.value,
                "task_type": p.task_type.value,
            }
            for p in participants
        ]
    })
