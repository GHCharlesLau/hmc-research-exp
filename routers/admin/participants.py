"""Admin participant list and detail pages."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models.participant import Participant, Step
from models.experiment import ExperimentSession
from routers.admin.auth import require_admin

router = APIRouter()


@router.get("/admin/participants", response_class=HTMLResponse)
async def participants(request: Request, db: AsyncSession = Depends(get_db), _auth=Depends(require_admin)):
    if _auth:
        return _auth
    result = await db.execute(
        select(Participant).order_by(Participant.created_at.desc())
    )
    participant_rows = result.scalars().all()
    return request.app.state.templates.TemplateResponse("admin/participants.html", {
        "request": request,
        "nav": "participants",
        "participants": participant_rows,
        "step_order": [step.value for step in Step],
        "now": datetime.now(timezone.utc),
    })


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

    survey_data = None
    if participant.survey_response:
        sr = participant.survey_response
        survey_data = {col: getattr(sr, col) for col in sr.__table__.columns.keys() if col not in ('id', 'participant_id', 'created_at')}

    resume_url = f"/resume/{participant.resume_token}" if participant.resume_token else None

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
