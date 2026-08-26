"""Admin test-participant tools."""

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from models.participant import Participant, Step, TaskType, Partnership, PartnerLabel
from models.chat import ChatRoom, RoomType
from models.survey import SurveyResponse
from models.experiment import ExperimentSession
from services.matchmaking import dequeue_match, set_match_result
from services.chat_context import get_active_room
from services.participant_factory import generate_display_id
from config import get_settings
from routers.admin.auth import require_admin, _verify_admin_session
from dependencies.participant import AVAILABLE_AVATARS

router = APIRouter()
settings = get_settings()


@router.get("/admin/test-tools", response_class=HTMLResponse)
async def test_tools_page(request: Request, _auth=Depends(require_admin)):
    if _auth:
        return _auth
    return request.app.state.templates.TemplateResponse("admin/test_tools.html", {
        "request": request,
        "nav": "test-tools",
        "demo_mode": settings.DEMO_MODE,
    })


async def _ensure_hmc_room(db: AsyncSession, participant: Participant) -> None:
    existing = await get_active_room(db, participant.id, participant.current_round)
    if existing:
        return
    room = ChatRoom(
        participant_id=participant.id,
        room_type=RoomType.HMC,
        round_number=participant.current_round,
        room_id=str(uuid.uuid4())[:8],
    )
    db.add(room)


@router.post("/api/admin/test/participant")
async def create_test_participant(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
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

    if not nickname or len(nickname) > 50:
        return JSONResponse({"detail": "Nickname must be 1-50 characters"}, status_code=400)
    if avatar not in AVAILABLE_AVATARS:
        return JSONResponse({"detail": "Invalid avatar"}, status_code=400)

    try:
        tt = TaskType(str(task_type))
        ps = Partnership(str(partnership))
        pl = PartnerLabel(str(partner_label))
        step = Step(str(start_step))
    except ValueError as e:
        return JSONResponse({"detail": f"Invalid value: {e}"}, status_code=400)

    display_id = await generate_display_id(db)
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

    step_order = list(Step)
    step_index = step_order.index(step)
    if step_index >= step_order.index(Step.instructions_r2):
        participant.current_round = 2
    else:
        participant.current_round = 1

    db.add(participant)
    await db.commit()
    await db.refresh(participant)

    if step in (Step.chat_r1, Step.chat_r2) and ps == Partnership.HMC:
        await _ensure_hmc_room(db, participant)
        await db.commit()
        await db.refresh(participant)

    url = f"/experiment/{participant.id}"
    return JSONResponse({
        "url": url,
        "display_id": display_id,
        "participant_id": str(participant.id),
        "task_type": participant.task_type.value,
        "partnership": participant.partnership.value,
        "partner_label": participant.partner_label.value,
        "current_step": participant.current_step.value,
        "resume_url": f"/resume/{participant.resume_token}" if participant.resume_token else None,
    })


@router.post("/api/admin/test/set-step")
async def set_test_step(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
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
    old_step_index = step_order.index(participant.current_step)

    participant.current_step = step

    if new_step_index >= step_order.index(Step.instructions_r2):
        participant.current_round = 2
    elif new_step_index < step_order.index(Step.instructions_r2):
        participant.current_round = 1

    if new_step_index < old_step_index:
        for round_num in (1, 2):
            if new_step_index < step_order.index(Step.chat_r1) or round_num >= participant.current_round:
                rooms = await db.execute(
                    select(ChatRoom).where(
                        ChatRoom.participant_id == participant.id,
                        ChatRoom.round_number == round_num,
                        ChatRoom.is_active == True,  # noqa: E712
                    )
                )
                for room in rooms.scalars().all():
                    room.is_active = False
                    room.ended_at = datetime.now(timezone.utc)

    if step in (Step.chat_r1, Step.chat_r2) and participant.partnership == Partnership.HMC:
        await _ensure_hmc_room(db, participant)

    await db.commit()
    return JSONResponse({"detail": f"Step set to {step.value}"})


@router.get("/api/admin/test/hhc-queues")
async def get_hhc_queues(request: Request):
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    from services.matchmaking import get_all_queue_members
    queues = await get_all_queue_members()
    return JSONResponse({"queues": queues})


@router.post("/api/admin/test/clear-queue")
async def clear_hhc_queue(request: Request):
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
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    form = await request.form()
    p1_id = form.get("participant1_id", "")
    p2_id = form.get("participant2_id", "")

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

    task_type = p1.task_type.value
    await dequeue_match(p1_id, round_number, task_type)
    await dequeue_match(p2_id, round_number, task_type)

    room_id = f"hhc-{round_number}-{p1_id[:8]}-{p2_id[:8]}"
    room1 = ChatRoom(
        participant_id=uuid1,
        room_type=RoomType.HHC,
        round_number=round_number,
        room_id=room_id,
        partner_id=uuid2,
    )
    room2 = ChatRoom(
        participant_id=uuid2,
        room_type=RoomType.HHC,
        round_number=round_number,
        room_id=room_id,
        partner_id=uuid1,
    )
    db.add(room1)
    db.add(room2)

    p1.partner_id = uuid2
    p2.partner_id = uuid1
    p1.current_step = Step.chat_r1 if round_number == 1 else Step.chat_r2
    p2.current_step = Step.chat_r1 if round_number == 1 else Step.chat_r2
    p1.current_round = round_number
    p2.current_round = round_number
    p1.hhc_fallback = False
    p2.hhc_fallback = False

    await db.commit()
    await db.refresh(room1)
    await db.refresh(room2)

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
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    form = await request.form()
    task_type = form.get("task_type", "emotionTask")

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

    id1 = uuid.uuid4()
    id2 = uuid.uuid4()
    display_id1 = await generate_display_id(db)

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
    await db.flush()

    display_id2 = await generate_display_id(db)

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

    room_id = f"hhc-{round_number}-{str(id1)[:8]}-{str(id2)[:8]}"
    room1 = ChatRoom(
        participant_id=id1,
        room_type=RoomType.HHC,
        round_number=round_number,
        room_id=room_id,
        partner_id=id2,
    )
    room2 = ChatRoom(
        participant_id=id2,
        room_type=RoomType.HHC,
        round_number=round_number,
        room_id=room_id,
        partner_id=id1,
    )
    db.add(room1)
    db.add(room2)

    p1.partner_id = id2
    p2.partner_id = id1

    await db.commit()
    await db.refresh(room1)
    await db.refresh(room2)

    await set_match_result(str(id1), str(room1.id), room_id)
    await set_match_result(str(id2), str(room2.id), room_id)

    return JSONResponse({
        "room_id": room_id,
        "task_type": tt.value,
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

    if participant.partner_id:
        partner = await db.get(Participant, participant.partner_id)
        if partner:
            partner.partner_id = None

    for round_num in (1, 2):
        await dequeue_match(str(participant_id), round_num, participant.task_type.value)

    result = await db.execute(
        select(ChatRoom).where(ChatRoom.participant_id == participant_id)
    )
    for room in result.scalars().all():
        await db.delete(room)

    sr_result = await db.execute(
        select(SurveyResponse).where(SurveyResponse.participant_id == participant_id)
    )
    for sr in sr_result.scalars().all():
        await db.delete(sr)

    sess_result = await db.execute(
        select(ExperimentSession).where(ExperimentSession.participant_id == participant_id)
    )
    for s in sess_result.scalars().all():
        await db.delete(s)

    display_id = participant.display_id
    await db.delete(participant)
    await db.commit()

    return JSONResponse({"detail": f"Deleted test participant {display_id}"})


@router.post("/api/admin/test/cleanup-all")
async def cleanup_all_test_data(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    result = await db.execute(
        select(Participant).where(Participant.is_test == True)  # noqa: E712
    )
    test_participants = result.scalars().all()
    count = len(test_participants)

    if count == 0:
        return JSONResponse({"detail": "No test participants to delete"})

    for p in test_participants:
        rooms = await db.execute(
            select(ChatRoom).where(ChatRoom.participant_id == p.id)
        )
        for room in rooms.scalars().all():
            await db.delete(room)

        sr = await db.execute(
            select(SurveyResponse).where(SurveyResponse.participant_id == p.id)
        )
        for s in sr.scalars().all():
            await db.delete(s)

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
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    result = await db.execute(
        select(func.count(Participant.id)).where(Participant.is_test == True)  # noqa: E712
    )
    count = result.scalar() or 0
    return JSONResponse({"count": count})


@router.get("/api/admin/test/participants")
async def list_test_participants(request: Request, db: AsyncSession = Depends(get_db)):
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    result = await db.execute(
        select(Participant)
        .where(Participant.is_test == True)  # noqa: E712
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
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error

    display_id = await generate_display_id(db)
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
    display_id1 = await generate_display_id(db)
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
    display_id2 = await generate_display_id(db)
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
        "task_type": tt.value,
    })


@router.post("/api/admin/test/next-step")
async def next_test_step(
    request: Request, db: AsyncSession = Depends(get_db),
):
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

    if next_step == Step.instructions_r2:
        participant.current_round = 2

    if next_step in (Step.chat_r1, Step.chat_r2) and participant.partnership == Partnership.HMC:
        await _ensure_hmc_room(db, participant)

    await db.commit()
    return JSONResponse({
        "detail": f"Advanced to {next_step.value}",
        "current_step": next_step.value,
    })


@router.get("/api/admin/test/participant-options")
async def test_participant_options(request: Request, db: AsyncSession = Depends(get_db)):
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error
    result = await db.execute(
        select(Participant)
        .where(Participant.is_test == True)  # noqa: E712
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
