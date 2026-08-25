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
from models.participant import Participant, Step
from models.chat import ChatRoom, ChatMessage, RoomType, SenderRole
from services import llm, matchmaking
from services.chat_context import (
    can_skip_min_turns,
    get_active_room,
    get_shared_turns,
    is_force_chatbot,
    mark_chat_exit_eligible,
    partner_display_assets,
    remaining_chat_seconds,
)
from services.chat_settings import get_chat_limits
from services.monitoring import log_event
from services.auth import verify_ws_participant
from dependencies.participant import (
    get_participant,
    redirect_to_step,
    participant_to_dict,
    advance_step,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# -- Pairing Confirmed (HMC only) --------------------------

@router.get("/pairing", response_class=HTMLResponse)
async def pairing_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    # Only for HMC participants heading to chat
    if participant.current_step not in (Step.chat_r1, Step.chat_r2):
        return await redirect_to_step(participant, db)

    p = participant_to_dict(participant)

    # Forced chatbot identity in R2 = participant has no real partner (timeout
    # fallback or HMC carryover). Derived from durable participant state.
    force_chatbot = is_force_chatbot(participant)
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
    participant = await get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    round_number = participant.current_round

    # BUG-D2 FIX: Reuse existing active room instead of creating a duplicate.
    room = await get_active_room(db, participant.id, round_number)
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


# -- Waiting Room (HHC only) -------------------------------

@router.get("/waiting", response_class=HTMLResponse)
async def waiting_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    if participant.current_step not in (Step.chat_r1, Step.chat_r2):
        return await redirect_to_step(participant, db)

    # BUG-01 FIX: Allow all participants (HMC and HHC) to access waiting room
    # HMC participants will use WebSocket fake waiting room logic (ws.py)
    # HHC participants will use real matchmaking logic

    p = participant_to_dict(participant)
    round_number = participant.current_round

    return request.app.state.templates.TemplateResponse("waiting.html", {
        "request": request,
        "p": p,
        "round_number": round_number,
    })


# -- Chat Page ----------------------------------------------

@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    if participant.current_step not in (Step.chat_r1, Step.chat_r2):
        return await redirect_to_step(participant, db)

    room_id = request.query_params.get("room")

    # BUG-02 FIX: If no room param, look up active room from DB
    if not room_id:
        room = await get_active_room(db, participant.id, participant.current_round)
        if room:
            return RedirectResponse(url=f"/chat?room={room.id}", status_code=303)
        return RedirectResponse(url="/waiting", status_code=303)

    # Verify room belongs to this participant
    result = await db.execute(
        select(ChatRoom).where(ChatRoom.id == uuid.UUID(room_id), ChatRoom.participant_id == participant.id)
    )
    room = result.scalar_one_or_none()
    if not room or not room.is_active:
        return RedirectResponse(url="/instructions", status_code=303)

    p = participant_to_dict(participant)

    # Load message history
    messages = []
    for msg in room.messages:
        messages.append({
            "sender_role": msg.sender_role.value,
            "text": msg.text,
            "turn_number": msg.turn_number,
            "msg_id": str(msg.id),
        })

    initial_shared_turns = await get_shared_turns(room, participant)
    force_chatbot = is_force_chatbot(participant, room)

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

    limits = get_chat_limits()
    time_remaining = remaining_chat_seconds(room)
    show_retry_dialog = time_remaining <= 0 and initial_shared_turns < limits.min_turns
    if show_retry_dialog:
        await mark_chat_exit_eligible(participant.id, room.round_number)

    partner_avatar, partner_name = partner_display_assets(
        force_chatbot=force_chatbot,
        is_r1=room.round_number == 1,
        partner_info=partner_info,
        partner_label=p["partner_label"],
    )
    chat_config = {
        "messages": messages,
        "initialSharedTurns": initial_shared_turns,
        "minTurns": limits.min_turns,
        "maxTurns": limits.max_turns,
        "timeRemaining": time_remaining,
        "showRetryDialog": show_retry_dialog,
        "roomId": str(room.id),
        "userAvatar": f"/static/avatar/{p['avatar'] or 'lion.png'}",
        "userName": p["nickname"] or "",
        "partnerAvatar": partner_avatar,
        "partnerName": partner_name,
    }

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
        "min_turns": limits.min_turns,
        "max_turns": limits.max_turns,
        "max_duration": time_remaining,
        "force_chatbot": force_chatbot,
        "partner_info": partner_info,
        "show_retry_dialog": show_retry_dialog,
        "chat_config": chat_config,
    })


# -- End Chat (HTTP) ---------------------------------------

@router.post("/chat/end")
async def end_chat(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    partner_left = request.query_params.get("partner_left") == "1"
    is_timeout = request.query_params.get("timeout") == "1"
    is_retry = request.query_params.get("retry") == "1"
    is_dropout = request.query_params.get("dropout") == "1"
    shared_turns_at_exit = 0
    skip_min_turns = False

    try:
        room = await get_active_room(db, participant.id, participant.current_round)
        if room:
            skip_min_turns = await can_skip_min_turns(
                room,
                participant,
                partner_left=partner_left,
                is_timeout=is_timeout,
                is_retry=is_retry,
                is_dropout=is_dropout,
            )
            if not skip_min_turns and (is_retry or is_dropout):
                return RedirectResponse(url=f"/chat?room={room.id}", status_code=303)
            if not skip_min_turns:
                limits = get_chat_limits()
                actual_exchanges = await get_shared_turns(room, participant)
                shared_turns_at_exit = actual_exchanges
                if actual_exchanges < limits.min_turns:
                    return RedirectResponse(url=f"/chat?room={room.id}", status_code=303)
            else:
                shared_turns_at_exit = await get_shared_turns(room, participant)
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
            if room.room_type == RoomType.HHC and room.room_id and participant.partner_id:
                try:
                    r = await matchmaking.get_redis()
                    partner_ws = await r.get(f"hhc_ws:{participant.partner_id}")
                    if partner_ws:
                        await matchmaking.publish_chat_message(room.room_id, {
                            "type": "partner_left",
                            "sender_id": str(participant.id),
                            "sender_name": participant.nickname or participant.display_id,
                        })
                        logger.info(f"Published partner_left for {participant.display_id} in room {room.room_id}")
                    else:
                        logger.info(f"Skipped partner_left for {participant.display_id}: partner {participant.partner_id} not connected")
                except Exception as pub_err:
                    logger.error(f"Failed to publish partner_left: {pub_err}")

    except Exception as e:
        logger.error(f"end_chat error for participant {participant.id}: {e}", exc_info=True)
        # On error, still try to deactivate room and notify partner
        # but do NOT auto-advance step — let the retry/dropout logic below handle it
        try:
            await db.rollback()
        except Exception:
            pass

    # -- Retry / Dropout / Normal advancement (outside try/except) --
    # These must be OUTSIDE the try block so that exceptions in room
    # deactivation (Redis down, log failure, etc.) don't skip the
    # participant's explicit choice.

    if is_timeout:
        limits = get_chat_limits()
        if shared_turns_at_exit < limits.min_turns:
            participant.is_timeout = True

    if is_dropout:
        participant.is_dropout = True
        try:
            await db.commit()
        except Exception:
            pass
        try:
            await log_event(db, participant.id, "dropout", participant.current_step.value, {
                "round_number": participant.current_round,
                "shared_turns_at_dropout": shared_turns_at_exit,
            })
        except Exception:
            pass
        return request.app.state.templates.TemplateResponse("end_no_consent.html", {
            "request": request,
            "is_dropout": True,
        })

    if is_retry:
        try:
            if participant.current_round == 1:
                await advance_step(participant, Step.instructions_r1, db, round_number=1)
            else:
                await advance_step(participant, Step.instructions_r2, db, round_number=2)
            await log_event(db, participant.id, "chat_retry", participant.current_step.value, {
                "round_number": participant.current_round,
            })
        except Exception as e:
            logger.error(f"chat_retry error: {e}", exc_info=True)
        return RedirectResponse(url="/instructions", status_code=303)

    # BUG-C4 FIX: only advance if still at a chat step
    if participant.current_step in (Step.chat_r1, Step.chat_r2):
        if participant.current_round == 1:
            await advance_step(participant, Step.instructions_r2, db, round_number=2)
            return RedirectResponse(url="/instructions", status_code=303)
        else:
            await advance_step(participant, Step.survey_prompt, db)
            return RedirectResponse(url="/survey/prompt", status_code=303)
    else:
        # Already advanced (e.g., by a concurrent POST) — just redirect
        return await redirect_to_step(participant, db)


# -- WebSocket Chat ----------------------------------------

@router.websocket("/ws/chat/{room_uuid}")
async def chat_websocket(websocket: WebSocket, room_uuid: str):
    from database import AsyncSessionLocal

    await websocket.accept()

    db = AsyncSessionLocal()
    try:
        try:
            room_id = uuid.UUID(room_uuid)
        except ValueError:
            await websocket.close(code=4004, reason="Invalid room")
            return

        room = await db.get(ChatRoom, room_id)
        if not room or not room.is_active:
            await websocket.close(code=4004, reason="Room not found or inactive")
            return

        participant = await db.get(Participant, room.participant_id)
        if not participant:
            await websocket.close(code=4004, reason="Participant not found")
            return

        if not await verify_ws_participant(websocket, participant.id):
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

    # Fetch R1 chat context for injection (only applicable in R2 with chatbot label)
    r1_context: str | None = None
    if participant.current_round == 2 and participant.partner_label.value == "chatbot":
        try:
            r1_context = await llm.get_r1_chat_context(db, participant.id, participant.partner_label.value)
            if r1_context:
                logger.info(f"R1 context loaded for {participant.display_id} ({len(r1_context)} chars)")
        except Exception as e:
            logger.error(f"Failed to load R1 context for {participant.display_id}: {e}", exc_info=True)
            r1_context = None

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
                max_turns = get_chat_limits().max_turns
                if exchange_count < max_turns:
                    # In R2, an HMC chat means the deception is over — force
                    # the chatbot prompt (CHARACTER_PROMPT_A/B), never Tommy.
                    # We are already inside _handle_hmc_chat, so room is HMC
                    # by construction; the round check alone is sufficient.
                    effective_partner_label = participant.partner_label.value
                    if participant.current_round == 2:
                        effective_partner_label = "chatbot"
                        logger.info(f"Round 2 HMC: forcing chatbot prompt for {participant.id}")

                    llm_response = await llm.call_llm(
                        db,
                        participant.task_type.value,
                        effective_partner_label,
                        chat_history,
                        r1_context=r1_context,
                        round_number=participant.current_round,
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
                        "r1_context_injected": r1_context is not None,
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
                            # BUG-17 FIX: Partner ended chat — notify and allow exit.
                            # Skip self-notification (sender_id matches this participant).
                            if data.get("sender_id") != str(participant.id):
                                await mark_chat_exit_eligible(participant.id, room.round_number)
                                await websocket.send_json(data)
                            else:
                                logger.debug(f"Skipped self partner_left for {participant.display_id}")
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

                    # Sanitize user input to prevent XSS — never fall back to raw text
                    clean_text = bleach.clean(text, tags=[], strip=True)

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

                    hhc_max = get_chat_limits().max_turns
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
                    shared_turns = await get_shared_turns(room, participant)
                    for msg in room.messages:
                        await websocket.send_json({
                            "type": "message",
                            "msg_id": str(msg.id),
                            "sender_role": msg.sender_role.value,
                            "text": msg.text,
                            "turn_number": msg.turn_number,
                            "shared_turns": shared_turns,
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
