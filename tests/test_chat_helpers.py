from unittest.mock import patch

import pytest

from models.chat import RoomType
from models.participant import TaskType
from services.chat_context import (
    compute_shared_turns,
    hmc_shared_turns,
    is_force_chatbot,
    partner_display_assets,
)
from services.chat_settings import get_chat_limits
from services.llm import get_prompt_key
from services.matchmaking import _queue_key, can_pair_participants


class _P:
    def __init__(self, current_round=1, partner_id=None):
        self.current_round = current_round
        self.partner_id = partner_id


class _Room:
    def __init__(self, room_type):
        self.room_type = room_type


def test_compute_shared_turns_is_min():
    assert compute_shared_turns(5, 3) == 3
    assert compute_shared_turns(0, 4) == 0


def test_hmc_shared_turns_is_half():
    assert hmc_shared_turns(10) == 5
    assert hmc_shared_turns(3) == 1


def test_force_chatbot_pairing_without_partner():
    assert is_force_chatbot(_P(current_round=2, partner_id=None)) is True
    assert is_force_chatbot(_P(current_round=2, partner_id="x")) is False
    assert is_force_chatbot(_P(current_round=1, partner_id=None)) is False


def test_force_chatbot_chat_page_uses_room_type():
    p = _P(current_round=2, partner_id="x")
    assert is_force_chatbot(p, _Room(RoomType.HMC)) is True
    assert is_force_chatbot(p, _Room(RoomType.HHC)) is False


def test_partner_display_r2_force_chatbot_is_mybot():
    avatar, name = partner_display_assets(
        force_chatbot=True, is_r1=False, partner_info=None, partner_label="human"
    )
    assert name == "MyBot"
    assert avatar.endswith("myBot.png")


def test_partner_display_r1_human_label_without_partner_is_tommy():
    avatar, name = partner_display_assets(
        force_chatbot=False, is_r1=True, partner_info=None, partner_label="human"
    )
    assert name == "Tommy"
    assert avatar.endswith("fox.png")


def test_get_chat_limits_demo_vs_prod():
    with patch("services.chat_settings.get_settings") as mock_settings:
        mock_settings.return_value.DEMO_MODE = False
        mock_settings.return_value.MIN_TURNS = 5
        mock_settings.return_value.MAX_TURNS = 15
        mock_settings.return_value.MAX_DURATION = 600
        mock_settings.return_value.HHC_TIMEOUT = 120
        limits = get_chat_limits()
        assert limits.min_turns == 5
        assert limits.max_turns == 15
        assert limits.max_duration == 600
        assert limits.max_duration_minutes == 10

    with patch("services.chat_settings.get_settings") as mock_settings:
        mock_settings.return_value.DEMO_MODE = True
        mock_settings.return_value.DEMO_MIN_TURNS = 2
        mock_settings.return_value.DEMO_MAX_TURNS = 5
        mock_settings.return_value.DEMO_MAX_DURATION = 300
        mock_settings.return_value.DEMO_HHC_TIMEOUT = 10
        limits = get_chat_limits()
        assert limits.min_turns == 2
        assert limits.hhc_timeout == 10


class _PairP:
    def __init__(self, task_type, partner_id=None, pid="a"):
        self.task_type = task_type
        self.partner_id = partner_id
        self.id = pid


def test_can_pair_rejects_different_task_types():
    p1 = _PairP(TaskType.emotionTask, pid="1")
    p2 = _PairP(TaskType.functionTask, pid="2")
    assert can_pair_participants(p1, p2, 1) == "task_type_mismatch"
    assert can_pair_participants(p1, p2, 2) == "task_type_mismatch"


def test_can_pair_same_task_allows_r1_and_new_r2_partner():
    p1 = _PairP(TaskType.functionTask, partner_id="other", pid="1")
    p2 = _PairP(TaskType.functionTask, partner_id="someone", pid="2")
    assert can_pair_participants(p1, p2, 1) is None
    assert can_pair_participants(p1, p2, 2) is None


def test_can_pair_rejects_r1_partners_in_round_2():
    p1 = _PairP(TaskType.emotionTask, partner_id="2", pid="1")
    p2 = _PairP(TaskType.emotionTask, partner_id="1", pid="2")
    assert can_pair_participants(p1, p2, 1) is None
    assert can_pair_participants(p1, p2, 2) == "r1_partners"


def test_prompt_key_keeps_function_task_in_round_2_chatbot():
    assert get_prompt_key("functionTask", "chatbot") == "CHARACTER_PROMPT_B"
    assert get_prompt_key("emotionTask", "chatbot") == "CHARACTER_PROMPT_A"
    assert get_prompt_key(TaskType.functionTask, "human") == "CHARACTER_PROMPT_Bfake"


def test_queue_key_requires_task_type():
    with pytest.raises(ValueError):
        _queue_key("", 1)
    assert _queue_key("emotionTask", 2) == "matchmaking:queue:emotionTask:round_2"


def test_should_remove_from_queue_rules():
    from models.participant import Step
    from services.monitoring import should_remove_from_queue

    class _Q:
        def __init__(self, step=Step.chat_r1, timeout=False, dropout=False, finished=False):
            self.current_step = step
            self.is_timeout = timeout
            self.is_dropout = dropout
            self.is_finished = finished

    assert should_remove_from_queue(None) is True
    assert should_remove_from_queue(_Q(timeout=True)) is True
    assert should_remove_from_queue(_Q(dropout=True)) is True
    assert should_remove_from_queue(_Q(finished=True)) is True
    assert should_remove_from_queue(_Q(step=Step.instructions_r1)) is True
    assert should_remove_from_queue(_Q(step=Step.chat_r1), queued_seconds=10) is False
    assert should_remove_from_queue(_Q(step=Step.chat_r1), queued_seconds=200, hhc_timeout=120) is True


def test_hmc_shared_turns_uses_complete_exchanges_when_messages_loaded():
    import asyncio
    from types import SimpleNamespace

    from models.chat import SenderRole
    from services.chat_context import get_shared_turns

    room = SimpleNamespace(
        room_type=RoomType.HMC,
        turn_count=3,
        messages=[
            SimpleNamespace(sender_role=SenderRole.user),
            SimpleNamespace(sender_role=SenderRole.user),
            SimpleNamespace(sender_role=SenderRole.user),
        ],
        room_id=None,
    )
    participant = SimpleNamespace(id=None, partner_id=None)
    assert asyncio.run(get_shared_turns(room, participant)) == 0


def test_hmc_echoes_user_messages_before_llm_replies():
    """Participants can send several messages while the LLM is still working."""
    import asyncio
    import json
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import WebSocketDisconnect
    from routers.chat import _handle_hmc_chat

    class FakeWS:
        def __init__(self):
            self.incoming = asyncio.Queue()
            self.sent = []

        async def receive_text(self):
            item = await self.incoming.get()
            if isinstance(item, BaseException):
                raise item
            return item

        async def send_json(self, payload):
            self.sent.append(payload)

    class FakeSessionCM:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, *args):
            return False

    async def _run():
        ws = FakeWS()
        room_id = uuid.uuid4()
        room = SimpleNamespace(id=room_id, messages=[], turn_count=0)
        participant = SimpleNamespace(
            id=uuid.uuid4(),
            display_id="P-TEST",
            current_round=1,
            partner_label=SimpleNamespace(value="chatbot"),
            task_type=SimpleNamespace(value="emotionTask"),
            current_step=SimpleNamespace(value="chat_r1"),
        )
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock()

        llm_db = MagicMock()
        llm_db.add = MagicMock()
        llm_db.commit = AsyncMock()
        llm_db.rollback = AsyncMock()
        llm_db.execute = AsyncMock()
        llm_db.get = AsyncMock(return_value=None)
        llm_db.scalar = AsyncMock(return_value=None)

        async def slow_llm(*_args, **_kwargs):
            await asyncio.sleep(0.25)
            return "AI reply"

        limits = SimpleNamespace(max_turns=15)

        with (
            patch("routers.chat.get_chat_limits", return_value=limits),
            patch("routers.chat.llm.call_llm", side_effect=slow_llm),
            patch("routers.chat.log_event", new_callable=AsyncMock),
            patch("routers.chat.AsyncSessionLocal", lambda: FakeSessionCM(llm_db)),
        ):
            handler = asyncio.create_task(_handle_hmc_chat(ws, db, room, participant))
            await ws.incoming.put(json.dumps({"type": "message", "text": "hello"}))
            await ws.incoming.put(json.dumps({"type": "message", "text": "are you there"}))
            await asyncio.sleep(0.08)
            user_echoes = [m for m in ws.sent if m.get("sender_role") == "user"]
            partner_echoes = [m for m in ws.sent if m.get("sender_role") == "partner"]
            assert [m["text"] for m in user_echoes] == ["hello", "are you there"]
            assert partner_echoes == []

            await asyncio.sleep(0.7)
            partner_echoes = [m for m in ws.sent if m.get("sender_role") == "partner"]
            assert [m["text"] for m in partner_echoes] == ["AI reply", "AI reply"]

            await ws.incoming.put(WebSocketDisconnect())
            await asyncio.wait_for(handler, timeout=2)

    asyncio.run(_run())
