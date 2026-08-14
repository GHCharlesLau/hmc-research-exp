"""Session cookie signing and WebSocket participant binding."""

import hashlib
import hmac
import logging
import uuid

from fastapi import WebSocket
from fastapi.responses import Response

from config import get_settings

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "participant_id"
SESSION_COOKIE_MAX_AGE = 86400
ADMIN_COOKIE_NAME = "admin_token"
ADMIN_COOKIE_MAX_AGE = 86400
_SIG_LEN = 32


def sign_participant_id(participant_id: str) -> str:
    """Return ``{uuid}.{hmac}`` using SECRET_KEY."""
    sig = hmac.new(
        get_settings().SECRET_KEY.encode(),
        participant_id.encode(),
        hashlib.sha256,
    ).hexdigest()[:_SIG_LEN]
    return f"{participant_id}.{sig}"


def parse_participant_cookie(value: str | None) -> uuid.UUID | None:
    """Parse a signed (or legacy unsigned) participant_id cookie."""
    if not value:
        return None
    pid_str = value
    if "." in value:
        pid_str, sig = value.rsplit(".", 1)
        expected = hmac.new(
            get_settings().SECRET_KEY.encode(),
            pid_str.encode(),
            hashlib.sha256,
        ).hexdigest()[:_SIG_LEN]
        if not hmac.compare_digest(sig, expected):
            logger.warning("Invalid participant cookie signature")
            return None
    try:
        return uuid.UUID(pid_str)
    except ValueError:
        return None


def cookie_kwargs(*, max_age: int) -> dict:
    """Shared cookie flags: httponly, samesite=lax, secure in production."""
    settings = get_settings()
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": not settings.DEBUG,
        "max_age": max_age,
    }


def set_participant_cookie(response: Response, participant_id: uuid.UUID) -> Response:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        sign_participant_id(str(participant_id)),
        **cookie_kwargs(max_age=SESSION_COOKIE_MAX_AGE),
    )
    return response


def set_admin_cookie(response: Response, token: str) -> Response:
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        token,
        **cookie_kwargs(max_age=ADMIN_COOKIE_MAX_AGE),
    )
    return response


def get_ws_participant_id(websocket: WebSocket) -> uuid.UUID | None:
    """Read and verify the participant session cookie on a WebSocket."""
    return parse_participant_cookie(websocket.cookies.get(SESSION_COOKIE_NAME))


async def verify_ws_participant(
    websocket: WebSocket,
    expected_id: uuid.UUID,
) -> bool:
    """Close the socket and return False when the session does not match."""
    cookie_id = get_ws_participant_id(websocket)
    if cookie_id is None:
        await websocket.close(code=4001, reason="Authentication required")
        return False
    if cookie_id != expected_id:
        await websocket.close(code=4003, reason="Participant mismatch")
        return False
    return True
