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
