"""Effective chat limits (demo vs production) in one place."""

from dataclasses import dataclass

from config import get_settings


@dataclass(frozen=True)
class ChatLimits:
    min_turns: int
    max_turns: int
    max_duration: int  # seconds
    hhc_timeout: int  # seconds

    @property
    def max_duration_minutes(self) -> int:
        return self.max_duration // 60


def get_chat_limits() -> ChatLimits:
    """Return chat/matchmaking limits for the current DEMO_MODE setting."""
    settings = get_settings()
    if settings.DEMO_MODE:
        return ChatLimits(
            min_turns=settings.DEMO_MIN_TURNS,
            max_turns=settings.DEMO_MAX_TURNS,
            max_duration=settings.DEMO_MAX_DURATION,
            hhc_timeout=settings.DEMO_HHC_TIMEOUT,
        )
    return ChatLimits(
        min_turns=settings.MIN_TURNS,
        max_turns=settings.MAX_TURNS,
        max_duration=settings.MAX_DURATION,
        hhc_timeout=settings.HHC_TIMEOUT,
    )
