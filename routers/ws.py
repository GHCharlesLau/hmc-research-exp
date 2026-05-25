"""WebSocket router for matchmaking and admin monitoring."""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from database import AsyncSessionLocal
from models.participant import Participant, Step, Partnership
from models.chat import ChatRoom, ChatMessage, RoomType, SenderRole
from services import matchmaking
from services.monitoring import log_event
from config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


def _effective_hhc_timeout() -> int:
    """Return HHC timeout based on demo mode."""
    return settings.DEMO_HHC_TIMEOUT if settings.DEMO_MODE else settings.HHC_TIMEOUT


@router.websocket("/ws/matchmaking/{participant_id}/{round_number}")
async def matchmaking_websocket(websocket: WebSocket, participant_id: str, round_number: int):
    """WebSocket for HHC waiting room. Handles real matching (HHC) and fake matching (HMC round 1)."""
    await websocket.accept()

    db = AsyncSessionLocal()
    try:
        from uuid import UUID
        participant = await db.get(Participant, UUID(participant_id))
        if not participant:
            await websocket.close(code=4004)
            return

        task_type = participant.task_type.value

        # Check if already matched (e.g. reconnection after other handler matched)
        existing_match = await matchmaking.get_match_result(participant_id)
        if existing_match:
            await websocket.send_json({
                "type": "match_found",
                "room_id": existing_match["room_id"],
                "room_uuid": existing_match["room_uuid"],
            })
            return

        # Round 1 HMC: Fake waiting room (no real matching)
        if round_number == 1 and participant.partnership == Partnership.HMC:
            # Simulate waiting time (5-15 seconds random)
            import random
            fake_wait_time = random.uniform(5, 15)

            await websocket.send_json({"type": "status", "message": "Waiting for a partner..."})

            # Wait simulated time
            await asyncio.sleep(fake_wait_time)

            # BUG-D6 FIX: Check for existing active room before creating a new one.
            # Prevents duplicate rooms when user refreshes waiting page.
            import uuid
            existing_room = await db.execute(
                select(ChatRoom).where(
                    ChatRoom.participant_id == UUID(participant_id),
                    ChatRoom.round_number == round_number,
                    ChatRoom.is_active == True,
                )
            )
            room = existing_room.scalar_one_or_none()
            if not room:
                room_id = str(uuid.uuid4())[:8]
                room = ChatRoom(
                    participant_id=UUID(participant_id),
                    room_type=RoomType.HMC,
                    round_number=round_number,
                    room_id=room_id,
                    # BUG-D9: started_at set when WebSocket connects
                )
                db.add(room)
                await db.commit()
                await db.refresh(room)

            # Send fake match notification
            await websocket.send_json({
                "type": "match_found",
                "room_id": room.room_id or str(room.id),
                "room_uuid": str(room.id),
            })
            return

        # Real HHC matching (Round 1 HHC + Round 2 all)
        await matchmaking.enqueue_match(participant_id, round_number, task_type)

        # Notify participant
        await websocket.send_json({"type": "status", "message": "Waiting for a partner..."})

        # Start matchmaking checker
        match_found = False
        timeout_elapsed = 0
        check_interval = 3  # seconds
        hhc_timeout = _effective_hhc_timeout()

        while not match_found and timeout_elapsed < hhc_timeout:
            await asyncio.sleep(check_interval)
            timeout_elapsed += check_interval

            # First check: did the OTHER participant's handler already match us?
            match_result = await matchmaking.get_match_result(participant_id)
            if match_result:
                await websocket.send_json({
                    "type": "match_found",
                    "room_id": match_result["room_id"],
                    "room_uuid": match_result["room_uuid"],
                })
                match_found = True
                break

            # Second check: try to find a match ourselves
            match = await matchmaking.try_match(round_number, task_type)
            if match:
                p1_id, p2_id = match
                if participant_id in (p1_id, p2_id):
                    # Match found! Create rooms for both participants
                    other_id = p2_id if p1_id == participant_id else p1_id
                    match_found = True

                    # Create HHC rooms for both participants
                    room_id = f"hhc-{round_number}-{p1_id[:8]}-{p2_id[:8]}"

                    room_uuids = {}
                    for pid in (p1_id, p2_id):
                        # BUG-D6 FIX: Skip if room already exists for this participant+round
                        existing_hhc = await db.execute(
                            select(ChatRoom).where(
                                ChatRoom.participant_id == UUID(pid),
                                ChatRoom.round_number == round_number,
                                ChatRoom.is_active == True,
                            )
                        )
                        existing_room = existing_hhc.scalar_one_or_none()
                        if existing_room:
                            room_uuids[pid] = str(existing_room.id)
                            logger.info(f"Reusing existing HHC room for {pid}: {existing_room.id}")
                            continue
                        room = ChatRoom(
                            participant_id=UUID(pid),
                            room_type=RoomType.HHC,
                            round_number=round_number,
                            room_id=room_id,
                            # BUG-D9: started_at set when WebSocket connects
                        )
                        db.add(room)
                        room_uuids[pid] = None  # filled after commit

                    # Set partner references
                    from uuid import UUID as UUIDType
                    p1 = await db.get(Participant, UUIDType(p1_id))
                    p2 = await db.get(Participant, UUIDType(p2_id))
                    if p1 and p2:
                        p1.partner_id = p2.id
                        p2.partner_id = p1.id

                    await db.commit()

                    # Get room UUIDs after commit
                    for pid in (p1_id, p2_id):
                        result = await db.execute(
                            select(ChatRoom).where(
                                ChatRoom.participant_id == UUID(pid),
                                ChatRoom.round_number == round_number,
                                ChatRoom.is_active == True,
                            )
                        )
                        room = result.scalar_one_or_none()
                        if room:
                            room_uuids[pid] = str(room.id)

                    # Notify THIS participant via WebSocket
                    my_room_uuid = room_uuids.get(participant_id, "")
                    other_room_uuid = room_uuids.get(other_id, "")

                    await websocket.send_json({
                        "type": "match_found",
                        "room_id": room_id,
                        "room_uuid": my_room_uuid,
                    })

                    # Notify OTHER participant via Redis key (their polling loop will pick it up)
                    if other_room_uuid:
                        await matchmaking.set_match_result(other_id, other_room_uuid, room_id)

                    # Mark both participants as active in HHC chat (BUG-P02 fix: race condition prevention)
                    r = await matchmaking.get_redis()
                    await r.setex(f"hhc_ws:{p1_id}", 3600, "1")  # 1 hour TTL
                    await r.setex(f"hhc_ws:{p2_id}", 3600, "1")
                    logger.info(f"Marked {p1_id} and {p2_id} as active in HHC chat")

                    # Log match success event for both participants
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
                    # B2 fix: orphan prevention — re-enqueue the two popped participants
                    # so their own handlers can match them later
                    await matchmaking.enqueue_match(p1_id, round_number, task_type)
                    await matchmaking.enqueue_match(p2_id, round_number, task_type)
                    logger.info(f"Participant {participant_id} popped {p1_id} and {p2_id} but neither is self; re-enqueued")
                    # Continue waiting for own match
                    continue
            else:
                # Send queue update
                pos = await matchmaking.get_queue_position(participant_id, round_number, task_type)
                await websocket.send_json({
                    "type": "queue_update",
                    "position": pos,
                    "elapsed": timeout_elapsed,
                    "remaining": hhc_timeout - timeout_elapsed,
                })

        # Timeout: fallback to HMC
        if not match_found:
            # BUG-22 FIX: Re-check match result before fallback.
            # Race condition: the OTHER handler may have matched us just as our loop timed out.
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
            participant.partnership = Partnership.HMC

            # Round 2 fallback: force MyBot (chatbot) identity
            if round_number == 2:
                # Store in Redis that this is a forced chatbot fallback
                r = await matchmaking.get_redis()
                await r.setex(f"force_chatbot:{participant_id}", 86400, "1")  # 24h TTL
                logger.info(f"Round 2 fallback for {participant_id}: forcing chatbot identity")

            # BUG-D6 FIX: Check for existing active room before creating fallback room.
            import uuid
            existing_fb_room = await db.execute(
                select(ChatRoom).where(
                    ChatRoom.participant_id == UUID(participant_id),
                    ChatRoom.round_number == round_number,
                    ChatRoom.is_active == True,
                )
            )
            room = existing_fb_room.scalar_one_or_none()
            if not room:
                room = ChatRoom(
                    participant_id=UUID(participant_id),
                    room_type=RoomType.HMC,
                    round_number=round_number,
                    room_id=str(uuid.uuid4())[:8],
                    # BUG-D9: started_at set when WebSocket connects
                )
                db.add(room)
                await db.commit()
                await db.refresh(room)

            # Log match timeout event
            await log_event(db, UUID(participant_id), "match_timeout", f"chat_r{round_number}", {
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
        # Remove from queue to prevent matching with a disconnected participant
        try:
            await matchmaking.dequeue_match(participant_id, round_number, task_type)
        except Exception as e:
            logger.warning(f"Failed to dequeue participant {participant_id}: {e}")
    except Exception as e:
        logger.error(f"Matchmaking error for {participant_id}: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        await db.close()
