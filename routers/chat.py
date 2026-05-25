"""Chat router: pairing confirmed page + HTTP endpoints for chat."""

import asyncio
import uuid
import json
import logging
import bleach
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models.participant import Participant, Step, Partnership, PartnerLabel
from models.chat import ChatRoom, ChatMessage, RoomType, SenderRole
from models.experiment import ExperimentSession
from services import llm, matchmaking
from services.monitoring import log_event, log_step_entry
from config import get_settings
from routers.experiment import _get_participant, _redirect, _participant_to_dict, _advance_step

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


def _effective_max_turns() -> int:
    """Return max_turns based on demo mode."""
    return settings.DEMO_MAX_TURNS if settings.DEMO_MODE else settings.MAX_TURNS


# ── Pairing Confirmed (HMC only) ──────────────────────────

@router.get("/pairing", response_class=HTMLResponse)
async def pairing_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    # Only for HMC participants heading to chat
    if participant.current_step not in (Step.chat_r1, Step.chat_r2):
        return await _redirect(participant, db)

    p = _participant_to_dict(participant)

    # Check for forced chatbot identity (Round 2 fallback)
    force_chatbot = False
    if participant.current_round == 2:
        r = await matchmaking.get_redis()
        force_chatbot = await r.get(f"force_chatbot:{participant.id}") is not None
        if force_chatbot:
            logger.info(f"Participant {participant.id}: forcing chatbot identity for round 2 fallback")

    return request.app.state.templates.TemplateResponse("pairing_confirmed.html", {
        "request": request,
        "p": p,
        "round_number": participant.current_round,
        "force_chatbot": force_chatbot,
    })


@router.post("/pairing")
async def pairing_submit(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    round_number = participant.current_round

    # BUG-D2 FIX: Reuse existing active room instead of creating a duplicate.
    # Can happen when admin set-step already created a room, then user
    # navigates through pairing_confirmed → POST /pairing.
    existing = await db.execute(
        select(ChatRoom).where(
            ChatRoom.participant_id == participant.id,
            ChatRoom.round_number == round_number,
            ChatRoom.is_active == True,
        )
    )
    room = existing.scalar_one_or_none()
    if not room:
        room = ChatRoom(
            participant_id=participant.id,
            room_type=RoomType.HMC,
            round_number=round_number,
            room_id=str(uuid.uuid4())[:8],
            # BUG-D9: started_at set when WebSocket connects, not at room creation
        )
        db.add(room)
        await db.commit()
        await db.refresh(room)

    return RedirectResponse(url=f"/chat?room={room.id}", status_code=303)


# ── Waiting Room (HHC only) ───────────────────────────────

@router.get("/waiting", response_class=HTMLResponse)
async def waiting_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    if participant.current_step not in (Step.chat_r1, Step.chat_r2):
        return await _redirect(participant, db)

    # BUG-01 FIX: Allow all participants (HMC and HHC) to access waiting room
    # HMC participants will use WebSocket fake waiting room logic (ws.py:52-83)
    # HHC participants will use real matchmaking logic

    p = _participant_to_dict(participant)
    round_number = participant.current_round

    return request.app.state.templates.TemplateResponse("waiting.html", {
        "request": request,
        "p": p,
        "round_number": round_number,
    })


# ── Chat Page ──────────────────────────────────────────────

@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    if participant.current_step not in (Step.chat_r1, Step.chat_r2):
        return await _redirect(participant, db)

    room_id = request.query_params.get("room")

    # BUG-02 FIX: If no room param, look up active room from DB
    # This prevents redirect loops when _redirect() cannot find a room either
    if not room_id:
        result = await db.execute(
            select(ChatRoom).where(
                ChatRoom.participant_id == participant.id,
                ChatRoom.round_number == participant.current_round,
                ChatRoom.is_active == True,
            )
        )
        room = result.scalar_one_or_none()
        if room:
            return RedirectResponse(url=f"/chat?room={room.id}", status_code=303)
        # No active room exists — redirect to waiting room to trigger pairing/room creation
        return RedirectResponse(url="/waiting", status_code=303)

    # Verify room belongs to this participant
    result = await db.execute(
        select(ChatRoom).where(ChatRoom.id == uuid.UUID(room_id), ChatRoom.participant_id == participant.id)
    )
    room = result.scalar_one_or_none()
    if not room or not room.is_active:
        return RedirectResponse(url="/instructions", status_code=303)

    p = _participant_to_dict(participant)

    # Load message history
    messages = []
    for msg in room.messages:
        messages.append({
            "sender_role": msg.sender_role.value,
            "text": msg.text,
            "turn_number": msg.turn_number,
            "msg_id": str(msg.id),
        })

    # Calculate initial shared turns for both HMC and HHC
    if room.room_type == RoomType.HMC:
        # HMC: 1 exchange = 2 messages (user + partner), room.turn_count tracks all messages
        initial_shared_turns = room.turn_count // 2
    else:
        # HHC: 1 turn = each participant sends at least 1 message.
        # Use per-participant Redis counters for accuracy.
        my_msgs = await matchmaking.get_hhc_peer_msg_count(room.room_id, str(participant.id))
        partner_msgs = await matchmaking.get_hhc_peer_msg_count(room.room_id, str(participant.partner_id)) if participant.partner_id else 0
        initial_shared_turns = min(my_msgs, partner_msgs)

    # Check for forced chatbot identity (Round 2 fallback)
    force_chatbot = False
    if participant.current_round == 2:
        r = await matchmaking.get_redis()
        force_chatbot = await r.get(f"force_chatbot:{participant.id}") is not None

    # BUG-D8 FIX: For HHC rooms, fetch real partner info for avatar/name display.
    # Previously used partner_label which shows bot avatar for HHC real matches.
    partner_info = None  # {avatar, nickname} of the real partner
    if room.room_type == RoomType.HHC and participant.partner_id:
        partner_obj = await db.get(Participant, participant.partner_id)
        if partner_obj:
            partner_info = {
                "avatar": partner_obj.avatar or "lion.png",
                "nickname": partner_obj.nickname or partner_obj.display_id,
            }

    # BUG-D7 FIX: Calculate remaining time based on room start time.
    # Without this, page refresh resets the countdown to full max_duration,
    # allowing users to extend chat indefinitely by refreshing.
    max_duration = settings.DEMO_MAX_DURATION if settings.DEMO_MODE else settings.MAX_DURATION
    time_remaining = max_duration
    if room.started_at:
        elapsed = (datetime.now(timezone.utc) - room.started_at).total_seconds()
        time_remaining = max(0, int(max_duration - elapsed))

    return request.app.state.templates.TemplateResponse("chat.html", {
        "request": request,
        "p": p,
        "room": {
            "id": str(room.id),
            "room_id": room.room_id or "",
            "room_type": room.room_type.value,
            "round_number": room.round_number,
            "turn_count": room.turn_count,
        },
        "messages": json.dumps(messages),
        "initial_shared_turns": initial_shared_turns,
        "min_turns": settings.DEMO_MIN_TURNS if settings.DEMO_MODE else settings.MIN_TURNS,
        "max_turns": settings.DEMO_MAX_TURNS if settings.DEMO_MODE else settings.MAX_TURNS,
        "max_duration": time_remaining,  # Now sends remaining time, not total
        "force_chatbot": force_chatbot,
        "partner_info": partner_info,  # Real partner info for HHC rooms
    })


# ── End Chat (HTTP) ───────────────────────────────────────

@router.post("/chat/end")
async def end_chat(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    # BUG-17 FIX: partner_left flag allows skipping min_turns check
    # BUG-C1 FIX: timeout also allows skipping min_turns (user can't send more, no point blocking)
    partner_left = request.query_params.get("partner_left") == "1"
    is_timeout = request.query_params.get("timeout") == "1"
    skip_min_turns = partner_left or is_timeout

    try:
        # Find active room for current round
        result = await db.execute(
            select(ChatRoom).where(
                ChatRoom.participant_id == participant.id,
                ChatRoom.round_number == participant.current_round,
                ChatRoom.is_active == True,
            )
        )
        room = result.scalar_one_or_none()
        if room:
            # Server-side min_turns check (skip if partner already left or timeout)
            if not skip_min_turns:
                effective_min = settings.DEMO_MIN_TURNS if settings.DEMO_MODE else settings.MIN_TURNS
                if room.room_type == RoomType.HMC:
                    min_msg_count = effective_min * 2  # user + partner messages
                    actual_msg_count = room.turn_count
                    if actual_msg_count < min_msg_count:
                        return RedirectResponse(url=f"/chat?room={room.id}", status_code=303)
                else:
                    # BUG-H4 FIX: HHC min_turns should count exchanges (shared turns),
                    # not total messages. Use Redis shared counter for accuracy.
                    actual_exchanges = 0
                    try:
                        my_msgs = await matchmaking.get_hhc_peer_msg_count(room.room_id, str(participant.id))
                        partner_msgs = await matchmaking.get_hhc_peer_msg_count(room.room_id, str(participant.partner_id)) if participant.partner_id else 0
                        actual_exchanges = min(my_msgs, partner_msgs)
                    except Exception:
                        # Fallback: count total messages and divide by 2
                        actual_exchanges = len(room.messages) // 2
                    if actual_exchanges < effective_min:
                        return RedirectResponse(url=f"/chat?room={room.id}", status_code=303)
            room.is_active = False
            room.ended_at = datetime.now(timezone.utc)
            if room.started_at:
                room.duration_seconds = (room.ended_at - room.started_at).total_seconds()
            await db.commit()

            # Log chat end event
            await log_event(db, participant.id, "chat_ended", participant.current_step.value, {
                "room_type": room.room_type.value,
                "round_number": room.round_number,
                "turn_count": room.turn_count,
                "duration_seconds": room.duration_seconds,
            })

            # BUG-17 FIX: For HHC rooms, notify partner that this participant left
            if room.room_type == RoomType.HHC and room.room_id:
                try:
                    await matchmaking.publish_chat_message(room.room_id, {
                        "type": "partner_left",
                        "sender_id": str(participant.id),
                        "sender_name": participant.nickname or participant.display_id,
                    })
                    logger.info(f"Published partner_left for {participant.display_id} in room {room.room_id}")
                except Exception as pub_err:
                    logger.error(f"Failed to publish partner_left: {pub_err}")

        # Advance step — BUG-C4 FIX: only advance if still at a chat step
        # Prevents double-advance when two HHC participants both POST /chat/end
        if participant.current_step in (Step.chat_r1, Step.chat_r2):
            if participant.current_round == 1:
                await _advance_step(participant, Step.instructions_r2, db, round_number=2)
                return RedirectResponse(url="/instructions", status_code=303)
            else:
                await _advance_step(participant, Step.survey_prompt, db)
                return RedirectResponse(url="/survey/prompt", status_code=303)
        else:
            # Already advanced (e.g., by a concurrent POST) — just redirect
            return await _redirect(participant, db)

    except Exception as e:
        logger.error(f"end_chat error for participant {participant.id}: {e}", exc_info=True)
        # BUG-10 FIX: On error, still try to advance step so user isn't stuck
        try:
            if participant.current_round == 1:
                await _advance_step(participant, Step.instructions_r2, db)
            else:
                await _advance_step(participant, Step.survey_prompt, db)
            return RedirectResponse(url="/instructions", status_code=303)
        except Exception:
            return RedirectResponse(url="/", status_code=303)


# ── WebSocket Chat ────────────────────────────────────────

@router.websocket("/ws/chat/{room_uuid}")
async def chat_websocket(websocket: WebSocket, room_uuid: str):
    from fastapi import Depends
    from database import AsyncSessionLocal

    await websocket.accept()

    db = AsyncSessionLocal()
    try:
        room = await db.get(ChatRoom, uuid.UUID(room_uuid))
        if not room or not room.is_active:
            await websocket.close(code=4004, reason="Room not found or inactive")
            return

        participant = await db.get(Participant, room.participant_id)
        if not participant:
            await websocket.close(code=4004, reason="Participant not found")
            return

        # BUG-D9 FIX: Set started_at when WebSocket connects, not when room is created.
        # This prevents the timer from counting down before the user even opens the chat page.
        if not room.started_at:
            room.started_at = datetime.now(timezone.utc)
            await db.commit()

        # Handle HMC chat
        if room.room_type == RoomType.HMC:
            await _handle_hmc_chat(websocket, db, room, participant)
        # Handle HHC chat
        elif room.room_type == RoomType.HHC:
            await _handle_hhc_chat(websocket, db, room, participant)

    except Exception as e:
        logger.error(f"WebSocket error in room {room_uuid}: {e}")
    finally:
        await db.close()


async def _handle_hmc_chat(websocket: WebSocket, db, room: ChatRoom, participant: Participant):
    """Handle HMC (human-machine) chat via WebSocket.

    Turn counting matches HHC: 1 turn = 1 exchange (user message + LLM reply).
    Both messages in a pair share the same turn_number.
    """
    # BUG-09 FIX: Initialize exchange_count and chat_history from existing room messages
    # This ensures correct turn counting after page refresh / WebSocket reconnect
    chat_history: list[dict] = []
    exchange_count = room.turn_count // 2  # recover from existing messages
    for msg in room.messages:
        role = "user" if msg.sender_role == SenderRole.user else "assistant"
        chat_history.append({"role": role, "content": msg.text})

    while True:
        try:
            data = json.loads(await websocket.receive_text())
            msg_type = data.get("type")

            if msg_type == "message":
                text = data.get("text", "").strip()
                if not text:
                    continue

                # Sanitize user input to prevent XSS
                clean_text = bleach.clean(text, tags=[], strip=True)

                # Save user message
                room.turn_count += 1
                current_turn = exchange_count + 1  # turn number for this exchange
                user_msg = ChatMessage(
                    chat_room_id=room.id,
                    sender_role=SenderRole.user,
                    text=clean_text,
                    turn_number=current_turn,
                )
                db.add(user_msg)

                # Build chat history for LLM (use clean text)
                chat_history.append({"role": "user", "content": clean_text})

                await db.commit()

                # BUG-09 FIX: Include msg_id in echo for deduplication after reconnect
                await websocket.send_json({
                    "type": "message",
                    "msg_id": str(user_msg.id),
                    "sender_role": "user",
                    "text": clean_text,
                    "turn_number": current_turn,
                    "shared_turns": exchange_count,
                })

                # Call LLM (skip if max turns reached)
                max_turns = _effective_max_turns()
                if exchange_count < max_turns:
                    # Check for forced chatbot identity (Round 2 fallback)
                    effective_partner_label = participant.partner_label.value
                    if participant.current_round == 2:
                        r = await matchmaking.get_redis()
                        force_chatbot = await r.get(f"force_chatbot:{participant.id}") is not None
                        if force_chatbot:
                            effective_partner_label = "chatbot"
                            logger.info(f"Round 2 fallback: forcing chatbot prompt for {participant.id}")

                    llm_response = await llm.call_llm(
                        db,
                        participant.task_type.value,
                        effective_partner_label,
                        chat_history,
                    )

                    # Log LLM call event
                    llm_latency = 0.0
                    llm_success = llm_response != llm.FALLBACK_RESPONSE
                    await log_event(db, participant.id, "llm_call", participant.current_step.value, {
                        "success": llm_success,
                        "fallback": not llm_success,
                        "task_type": participant.task_type.value,
                        "partner_label": effective_partner_label,
                        "turn_number": current_turn,
                    })

                    room.turn_count += 1
                    partner_msg = ChatMessage(
                        chat_room_id=room.id,
                        sender_role=SenderRole.partner,
                        text=llm_response,
                        turn_number=current_turn,
                    )
                    db.add(partner_msg)
                    chat_history.append({"role": "assistant", "content": llm_response})
                    await db.commit()

                    exchange_count += 1  # one full exchange completed

                    # BUG-09 FIX: Include msg_id in partner reply for deduplication
                    await websocket.send_json({
                        "type": "message",
                        "msg_id": str(partner_msg.id),
                        "sender_role": "partner",
                        "text": llm_response,
                        "turn_number": current_turn,
                        "shared_turns": exchange_count,
                    })

                    # Check max turns — delay before ending so user can see the response
                    if exchange_count >= max_turns:
                        await asyncio.sleep(3)  # Give user time to read the final response
                        await websocket.send_json({"type": "chat_end", "reason": "max_turns"})
                        break
                else:
                    await websocket.send_json({"type": "chat_end", "reason": "max_turns"})
                    break

            elif msg_type == "history_request":
                # BUG-09 FIX: Include msg_id and shared_turns in history for deduplication
                for msg in room.messages:
                    await websocket.send_json({
                        "type": "message",
                        "msg_id": str(msg.id),
                        "sender_role": msg.sender_role.value,
                        "text": msg.text,
                        "turn_number": msg.turn_number,
                        "shared_turns": msg.turn_number,  # for HMC, turn_number == exchange count
                    })

        except json.JSONDecodeError:
            # B9: ignore malformed JSON, don't close connection
            continue
        except WebSocketDisconnect:
            logger.info(f"Participant {participant.display_id} disconnected from HMC room {room.id}")
            break
        except Exception as e:
            # BUG-23 FIX: Continue on transient errors instead of breaking.
            # Previously, any exception (DB error, Redis error, etc.) would kill the
            # entire HMC chat session. Now we log and continue, matching HHC resilience.
            logger.error(f"HMC chat error for {participant.display_id}: {e}", exc_info=True)
            try:
                await db.rollback()
            except Exception:
                pass
            continue


async def _handle_hhc_chat(websocket: WebSocket, db, room: ChatRoom, participant: Participant):
    """Handle HHC (human-human) chat via WebSocket.

    Uses shared turn counting (N6): 1 turn = 2 messages (one from each
    participant). Both messages in a pair share the same turn_number.
    The shared message count is tracked in Redis.

    IMPORTANT: listen_redis uses its own DB session (listen_db) to avoid
    cross-contamination with the main loop's session. Previously, both
    shared the same session, causing listen_redis's commit() to flush the
    main loop's pending room.turn_count changes, and rollback() to undo them.
    """
    import json as json_lib
    from database import AsyncSessionLocal as _ASL
    from services.matchmaking import get_redis, publish_chat_message, incr_hhc_message_count, incr_hhc_peer_msg_count, get_hhc_peer_msg_count, CHAT_CHANNEL_PREFIX
    from services.redis_pubsub import create_pubsub

    r = await get_redis()

    # BUG-21 FIX: Use generation counter to kill stale listen_redis coroutines.
    # When a new handler starts (page refresh / reconnect), it writes a new
    # generation ID to Redis. Old listen_redis() checks this value on every
    # message — if the generation changed, it stops immediately.
    handler_gen = str(uuid.uuid4())[:8]
    handler_gen_key = f"hhc_handler_gen:{participant.id}"
    await r.setex(handler_gen_key, 3600, handler_gen)

    # Mark THIS participant as active
    ws_key = f"hhc_ws:{participant.id}"
    await r.setex(ws_key, 3600, "1")

    if participant.partner_id:
        partner_ws_key = f"hhc_ws:{participant.partner_id}"
        partner_active = await r.get(partner_ws_key)
        if not partner_active:
            logger.info(f"Participant {participant.id} connected to HHC room, partner {participant.partner_id} not yet active")

    logger.info(f"HHC chat handler started: participant={participant.display_id}, room_id={room.room_id}")

    # BUG-11 FIX: Use create_pubsub() from redis_pubsub.py (redis-py 5.x compatible)
    # and wrap setup in try/except so pubsub failure doesn't kill the entire handler.
    channel = f"{CHAT_CHANNEL_PREFIX}{room.room_id}"
    redis_task = None

    try:
        pubsub_conn = await create_pubsub()
        ps = pubsub_conn.pubsub()
        await ps.subscribe(channel)
        logger.info(f"Subscribed to HHC channel: {channel}")
    except Exception as e:
        logger.error(f"Failed to subscribe to HHC channel {channel}: {e}", exc_info=True)
        ps = None
        pubsub_conn = None

    async def listen_redis():
        """Listen for messages from the other participant via Redis pubsub.

        BUG-12 FIX: Catch ALL exceptions (not just CancelledError) so that
        transient Redis errors don't silently kill partner message delivery.
        BUG-15 FIX: Save partner messages to local room so they persist on refresh.
        BUG-21 FIX: Check handler generation on every message to detect stale handler.
        BUG-DB1 FIX: Use a separate DB session to avoid cross-contamination with
        the main loop's session. Previously, listen_redis's commit() would also
        flush the main loop's pending room.turn_count changes, and its rollback()
        could undo them.
        """
        listen_db = _ASL()
        try:
            async for msg in ps.listen():
                # BUG-21 FIX: Stop if a newer handler has replaced us.
                # NOTE: decode_responses=True means r.get() returns str, not bytes.
                # Do NOT call .decode() on the result.
                try:
                    current_gen = await r.get(handler_gen_key)
                    if current_gen and current_gen != handler_gen:
                        logger.info(f"Stale listen_redis for {participant.display_id}, stopping (gen {handler_gen} != {current_gen})")
                        break
                except Exception:
                    pass

                if msg["type"] == "message":
                    try:
                        data = json_lib.loads(msg["data"])

                        if data.get("type") == "chat_end":
                            await websocket.send_json(data)
                            continue

                        if data.get("type") == "partner_left":
                            # BUG-17 FIX: Partner ended chat — notify and allow exit
                            await websocket.send_json(data)
                            continue

                        if data.get("sender_id") != str(participant.id):
                            # BUG-15 FIX: Save partner message to THIS participant's room
                            # so it persists across page refreshes.
                            # BUG-20 FIX: Check for duplicate before saving (prevents
                            # double-save when multiple WebSocket handlers exist due to
                            # page refresh race condition).
                            local_msg_id = data.get("msg_id")  # fallback to original
                            try:
                                # Deduplicate: check if this exact partner message already saved
                                existing = await listen_db.execute(
                                    select(ChatMessage).where(
                                        ChatMessage.chat_room_id == room.id,
                                        ChatMessage.sender_role == SenderRole.partner,
                                        ChatMessage.turn_number == data["turn_number"],
                                    )
                                )
                                already_saved = existing.scalar_one_or_none()
                                if already_saved:
                                    local_msg_id = str(already_saved.id)
                                    logger.debug(f"Skip duplicate partner message save for {participant.display_id}, turn={data['turn_number']}")
                                else:
                                    partner_msg = ChatMessage(
                                        chat_room_id=room.id,
                                        sender_role=SenderRole.partner,
                                        text=data["text"],
                                        turn_number=data["turn_number"],
                                    )
                                    listen_db.add(partner_msg)
                                    await listen_db.commit()
                                    local_msg_id = str(partner_msg.id)
                            except Exception as save_err:
                                logger.error(f"Failed to save partner message for {participant.display_id}: {save_err}")
                                try:
                                    await listen_db.rollback()
                                except Exception:
                                    pass

                            await websocket.send_json({
                                "type": "message",
                                "sender_role": "partner",
                                "sender_id": data.get("sender_id"),
                                "msg_id": local_msg_id,
                                "text": data["text"],
                                "turn_number": data["turn_number"],
                                "shared_turns": data.get("shared_turns", 0),
                            })
                            logger.info(f"HHC relay: participant={participant.display_id}, "
                                        f"from={data.get('sender_id', '?')[:8]}, "
                                        f"turn_number={data['turn_number']}, "
                                        f"shared_turns={data.get('shared_turns', 0)}")
                    except Exception as e:
                        logger.error(f"HHC listen_redis message processing error: {e}", exc_info=True)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"HHC listen_redis fatal error for {participant.display_id}: {e}", exc_info=True)
        finally:
            # BUG-11 FIX: Properly clean up pubsub resources in listen_redis's own finally block
            # BUG-H1 FIX: Also close the underlying Redis connection to prevent connection leak
            try:
                if ps:
                    await ps.unsubscribe(channel)
                    await ps.aclose()
            except Exception:
                pass
            try:
                if pubsub_conn:
                    await pubsub_conn.aclose()
            except Exception:
                pass
            # BUG-DB1 FIX: Close listen_redis's own DB session
            try:
                await listen_db.close()
            except Exception:
                pass

    if ps is not None:
        redis_task = asyncio.create_task(listen_redis())

    try:
        while True:
            try:
                data = json.loads(await websocket.receive_text())
                msg_type = data.get("type")

                if msg_type == "message":
                    text = data.get("text", "").strip()
                    if not text:
                        continue

                    # Sanitize user input to prevent XSS
                    try:
                        clean_text = bleach.clean(text, tags=[], strip=True)
                    except Exception as e:
                        logger.warning(f"bleach.clean() failed for {participant.display_id}: {e}, using raw text")
                        clean_text = text

                    # BUG-13 FIX: Wrap Redis incr in try/except — failure must NOT prevent echo
                    room.turn_count += 1
                    redis_count = None
                    my_count = 0
                    partner_count_val = 0
                    try:
                        # Shared counter: used as unique turn_number for dedup
                        redis_count = await incr_hhc_message_count(room.room_id)
                        shared_turn = redis_count
                        # Per-participant counter: used for actual turn counting
                        # 1 turn = each participant sends at least 1 message
                        my_count = await incr_hhc_peer_msg_count(room.room_id, str(participant.id))
                        partner_count_val = await get_hhc_peer_msg_count(room.room_id, str(participant.partner_id)) if participant.partner_id else 0
                        complete_turns = min(my_count, partner_count_val)
                    except Exception as e:
                        logger.error(f"Redis incr failed for {participant.display_id}: {e}", exc_info=True)
                        shared_turn = room.turn_count
                        complete_turns = max(room.turn_count - 1, 0)
                    logger.info(f"HHC msg: participant={participant.display_id}, room={room.room_id}, "
                                f"redis_count={redis_count}, turn_number={shared_turn}, "
                                f"my_count={my_count}, partner_count={partner_count_val}, "
                                f"complete_turns={complete_turns}, local_turn_count={room.turn_count}")
                    user_msg = ChatMessage(
                        chat_room_id=room.id,
                        sender_role=SenderRole.user,
                        text=clean_text,
                        turn_number=shared_turn,
                    )
                    db.add(user_msg)

                    # Wrap db.commit() in try/except with rollback on failure
                    try:
                        await db.commit()
                    except Exception as e:
                        logger.error(f"DB commit error for {participant.display_id}: {e}", exc_info=True)
                        try:
                            await db.rollback()
                        except Exception:
                            pass
                        continue

                    msg_id = str(user_msg.id)

                    # BUG-13 FIX: Wrap publish in try/except — failure must NOT prevent echo
                    try:
                        await publish_chat_message(room.room_id, {
                            "type": "message",
                            "sender_id": str(participant.id),
                            "sender_role": "user",
                            "msg_id": msg_id,
                            "text": clean_text,
                            "turn_number": shared_turn,
                            "shared_turns": complete_turns,
                        })
                    except Exception as e:
                        logger.error(f"Redis publish failed for {participant.display_id}: {e}", exc_info=True)

                    # Echo to self — ALWAYS executed regardless of Redis/DB issues above
                    await websocket.send_json({
                        "type": "message",
                        "sender_role": "user",
                        "sender_id": str(participant.id),
                        "msg_id": msg_id,
                        "text": clean_text,
                        "turn_number": shared_turn,
                        "shared_turns": complete_turns,
                    })

                    logger.info(f"HHC message echoed: participant={participant.display_id}, turn={shared_turn}")

                    hhc_max = _effective_max_turns()
                    if complete_turns >= hhc_max:
                        await asyncio.sleep(3)  # Give user time to read the final response
                        try:
                            await publish_chat_message(room.room_id, {
                                "type": "chat_end",
                                "reason": "max_turns",
                            })
                        except Exception as e:
                            logger.error(f"Redis publish chat_end failed: {e}")
                        await websocket.send_json({"type": "chat_end", "reason": "max_turns"})
                        break

                elif msg_type == "history_request":
                    # Reload messages from DB to include partner messages saved by listen_redis
                    await db.refresh(room, ["messages"])
                    total_msgs = len(room.messages)
                    for msg in room.messages:
                        await websocket.send_json({
                            "type": "message",
                            "msg_id": str(msg.id),
                            "sender_role": msg.sender_role.value,
                            "text": msg.text,
                            "turn_number": msg.turn_number,
                            "shared_turns": total_msgs // 2,
                        })

            except json.JSONDecodeError:
                continue
            except WebSocketDisconnect:
                logger.info(f"Participant {participant.display_id} disconnected from HHC room {room.room_id}")
                break
            except Exception as e:
                # BUG-12 FIX: Log with traceback and continue instead of breaking.
                # A single transient error should NOT kill the entire chat session.
                logger.error(f"HHC chat error for {participant.display_id}: {e}", exc_info=True)
                try:
                    await db.rollback()
                except Exception:
                    pass
                continue

    finally:
        try:
            await r.delete(f"hhc_ws:{participant.id}")
            await r.delete(handler_gen_key)
        except Exception as e:
            logger.warning(f"Failed to delete WebSocket active marker for {participant.id}: {e}")

        if redis_task is not None:
            redis_task.cancel()
            try:
                await redis_task
            except (asyncio.CancelledError, Exception):
                pass

        # pubsub cleanup handled by listen_redis's finally block
        # Do NOT close r (shared pool from get_redis()) — it's global and must persist
