"""Admin dashboard pages and polling APIs."""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from database import get_db
from models.participant import Participant, Step
from models.chat import ChatRoom
from models.experiment import ExperimentSession
from services.chat_settings import get_chat_limits
from services.monitoring import detect_stuck_participants
from routers.admin.auth import require_admin, _verify_admin_session

router = APIRouter()
logger = logging.getLogger(__name__)


async def _get_dashboard_stats(db: AsyncSession) -> dict:
    """Shared stats query for dashboard page and API."""
    total = await db.execute(select(func.count(Participant.id)))
    finished = await db.execute(
        select(func.count(Participant.id)).where(Participant.is_finished == True)  # noqa: E712
    )
    active = await db.execute(
        select(func.count(Participant.id)).where(Participant.is_finished == False)  # noqa: E712
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

    step_data = {}
    for step in Step:
        if step == Step.payment:
            continue
        result = await db.execute(
            select(func.count(Participant.id)).where(
                Participant.current_step == step,
                Participant.is_finished == False,  # noqa: E712
            )
        )
        count = result.scalar() or 0
        if count > 0:
            step_data[step.value] = count

    active_rooms_result = await db.execute(
        select(ChatRoom)
        .where(ChatRoom.is_active == True)  # noqa: E712
        .options(selectinload(ChatRoom.participant))
        .order_by(ChatRoom.started_at.desc())
    )
    all_active_rooms = list(active_rooms_result.scalars().all())

    max_duration = get_chat_limits().max_duration
    now = datetime.now(timezone.utc)
    stale_count = 0
    for room in all_active_rooms:
        if room.started_at and (now - room.started_at).total_seconds() > max_duration + 300:
            room.is_active = False
            room.ended_at = now
            room.duration_seconds = (now - room.started_at).total_seconds()
            if room.participant is not None:
                room.participant.is_timeout = True
            stale_count += 1
    if stale_count > 0:
        await db.commit()
        logger.info(f"Auto-deactivated {stale_count} stale chat rooms (exceeded max_duration)")
        active_rooms_result = await db.execute(
            select(ChatRoom)
            .where(ChatRoom.is_active == True)  # noqa: E712
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

    step_order = list(Step)
    active_participants_raw = await db.execute(
        select(Participant)
        .where(Participant.is_finished == False)  # noqa: E712
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
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    stats = await _get_dashboard_stats(db)
    return JSONResponse(stats)


@router.get("/api/admin/events")
async def event_feed(
    request: Request,
    db: AsyncSession = Depends(get_db),
    since: str | None = None,
    limit: int = 50,
):
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


@router.get("/api/admin/llm-stats")
async def llm_stats(request: Request, db: AsyncSession = Depends(get_db)):
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


@router.get("/api/admin/chat/{room_uuid}")
async def get_chat_messages(room_uuid: str, request: Request, db: AsyncSession = Depends(get_db)):
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
