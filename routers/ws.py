"""WebSocket router for matchmaking and admin monitoring."""

import asyncio
import logging
import uuid
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from database import AsyncSessionLocal
from models.participant import Participant, Partnership
from models.chat import ChatRoom, RoomType
from services import matchmaking
from services.auth import verify_ws_participant
from services.chat_context import get_active_room
from services.chat_settings import get_chat_limits
from services.monitoring import log_event

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/matchmaking/{participant_id}/{round_number}")
async def matchmaking_websocket(websocket: WebSocket, participant_id: str, round_number: int):
    """WebSocket for HHC waiting room. Handles real matching (HHC) and fake matching (HMC round 1)."""
    await websocket.accept()

    try:
        expected_id = UUID(participant_id)
    except ValueError:
        await websocket.close(code=4004)
        return

    if not await verify_ws_participant(websocket, expected_id):
        return

    db = AsyncSessionLocal()
    task_type = None
    try:
        participant = await db.get(Participant, expected_id)
        if not participant:
            await websocket.close(code=4004)
            return

        task_type = participant.task_type.value

        existing_match = await matchmaking.get_match_result(participant_id)
        if existing_match:
            await websocket.send_json({
                "type": "match_found",
                "room_id": existing_match["room_id"],
                "room_uuid": existing_match["room_uuid"],
            })
            return

        if round_number == 1 and participant.partnership == Partnership.HMC:
            import random
            fake_wait_time = random.uniform(5, 15)

            await websocket.send_json({"type": "status", "message": "Waiting for a partner..."})
            await asyncio.sleep(fake_wait_time)

            room = await get_active_room(db, expected_id, round_number)
            if not room:
                room_id = str(uuid.uuid4())[:8]
                room = ChatRoom(
                    participant_id=expected_id,
                    room_type=RoomType.HMC,
                    round_number=round_number,
                    room_id=room_id,
                )
                db.add(room)
                await db.commit()
                await db.refresh(room)

            await websocket.send_json({
                "type": "match_found",
                "room_id": room.room_id or str(room.id),
                "room_uuid": str(room.id),
            })
            return

        await matchmaking.enqueue_match(participant_id, round_number, task_type)
        await websocket.send_json({"type": "status", "message": "Waiting for a partner..."})

        match_found = False
        timeout_elapsed = 0
        check_interval = 3
        hhc_timeout = get_chat_limits().hhc_timeout

        while not match_found and timeout_elapsed < hhc_timeout:
            await asyncio.sleep(check_interval)
            timeout_elapsed += check_interval

            match_result = await matchmaking.get_match_result(participant_id)
            if match_result:
                await websocket.send_json({
                    "type": "match_found",
                    "room_id": match_result["room_id"],
                    "room_uuid": match_result["room_uuid"],
                })
                match_found = True
                break

            match = await matchmaking.try_match(round_number, task_type)
            if match:
                p1_id, p2_id = match
                if participant_id in (p1_id, p2_id):
                    other_id = p2_id if p1_id == participant_id else p1_id

                    p1 = await db.get(Participant, UUID(p1_id))
                    p2 = await db.get(Participant, UUID(p2_id))
                    if not p1 or not p2:
                        logger.warning(
                            "Match popped missing participant (%s, %s); re-enqueueing survivors",
                            p1_id,
                            p2_id,
                        )
                        if p1:
                            await matchmaking.enqueue_match(
                                p1_id, round_number, p1.task_type.value
                            )
                        if p2:
                            await matchmaking.enqueue_match(
                                p2_id, round_number, p2.task_type.value
                            )
                        continue

                    skip_reason = matchmaking.can_pair_participants(p1, p2, round_number)
                    if skip_reason:
                        logger.info(
                            "Skipping R%s match %s / %s: %s; re-enqueueing",
                            round_number,
                            p1_id,
                            p2_id,
                            skip_reason,
                        )
                        await matchmaking.enqueue_match(
                            p1_id, round_number, p1.task_type.value
                        )
                        await matchmaking.enqueue_match(
                            p2_id, round_number, p2.task_type.value
                        )
                        continue

                    match_found = True
                    room_id = f"hhc-{round_number}-{p1_id[:8]}-{p2_id[:8]}"
                    room_uuids = {}
                    for pid in (p1_id, p2_id):
                        existing_room = await get_active_room(db, UUID(pid), round_number)
                        if existing_room:
                            room_uuids[pid] = str(existing_room.id)
                            logger.info(f"Reusing existing HHC room for {pid}: {existing_room.id}")
                            continue
                        room = ChatRoom(
                            participant_id=UUID(pid),
                            room_type=RoomType.HHC,
                            round_number=round_number,
                            room_id=room_id,
                        )
                        db.add(room)
                        room_uuids[pid] = None

                    p1.partner_id = p2.id
                    p2.partner_id = p1.id

                    await db.commit()

                    for pid in (p1_id, p2_id):
                        room = await get_active_room(db, UUID(pid), round_number)
                        if room:
                            room_uuids[pid] = str(room.id)

                    my_room_uuid = room_uuids.get(participant_id, "")
                    other_room_uuid = room_uuids.get(other_id, "")

                    await websocket.send_json({
                        "type": "match_found",
                        "room_id": room_id,
                        "room_uuid": my_room_uuid,
                    })

                    if other_room_uuid:
                        await matchmaking.set_match_result(other_id, other_room_uuid, room_id)

                    r = await matchmaking.get_redis()
                    await r.setex(f"hhc_ws:{p1_id}", 3600, "1")
                    await r.setex(f"hhc_ws:{p2_id}", 3600, "1")
                    logger.info(f"Marked {p1_id} and {p2_id} as active in HHC chat")

                    if p1 and p2:
                        await log_event(db, p1.id, "match_success", f"chat_r{round_number}", {
                            "room_id": room_id,
                            "partner_display_id": p2.display_id,
                            "round": round_number,
                        })
                        await log_event(db, p2.id, "match_success", f"chat_r{round_number}", {
                            "room_id": room_id,
                            "partner_display_id": p1.display_id,
                            "round": round_number,
                        })

                    break
                else:
                    await matchmaking.enqueue_match(p1_id, round_number, task_type)
                    await matchmaking.enqueue_match(p2_id, round_number, task_type)
                    logger.info(f"Participant {participant_id} popped {p1_id} and {p2_id} but neither is self; re-enqueued")
                    continue
            else:
                pos = await matchmaking.get_queue_position(participant_id, round_number, task_type)
                await websocket.send_json({
                    "type": "queue_update",
                    "position": pos,
                    "elapsed": timeout_elapsed,
                    "remaining": hhc_timeout - timeout_elapsed,
                })

        if not match_found:
            late_match = await matchmaking.get_match_result(participant_id)
            if late_match:
                logger.info(f"Late match detected for {participant_id}, skipping fallback")
                await websocket.send_json({
                    "type": "match_found",
                    "room_id": late_match["room_id"],
                    "room_uuid": late_match["room_uuid"],
                })
                match_found = True

        if not match_found:
            await matchmaking.dequeue_match(participant_id, round_number, task_type)

            participant.hhc_fallback = True
            if round_number == 1:
                participant.partnership = Partnership.HMC

            if round_number == 2:
                logger.info(f"Round 2 fallback for {participant_id}: forcing chatbot identity")

            room = await get_active_room(db, expected_id, round_number)
            if not room:
                room = ChatRoom(
                    participant_id=expected_id,
                    room_type=RoomType.HMC,
                    round_number=round_number,
                    room_id=str(uuid.uuid4())[:8],
                )
                db.add(room)
                await db.commit()
                await db.refresh(room)

            await log_event(db, expected_id, "match_timeout", f"chat_r{round_number}", {
                "fallback_to": "HMC",
                "round": round_number,
                "forced_chatbot": round_number == 2,
            })

            await websocket.send_json({
                "type": "timeout_fallback",
                "room_uuid": str(room.id),
            })

    except WebSocketDisconnect:
        logger.info(f"Participant {participant_id} disconnected from matchmaking")
        if task_type:
            try:
                await matchmaking.dequeue_match(participant_id, round_number, task_type)
            except Exception as e:
                logger.warning(f"Failed to dequeue participant {participant_id}: {e}")
    except Exception as e:
        logger.error(f"Matchmaking error for {participant_id}: {e}")
        try:
            await websocket.send_json({"type": "error", "message": "Matchmaking error"})
        except Exception:
            pass
    finally:
        await db.close()
