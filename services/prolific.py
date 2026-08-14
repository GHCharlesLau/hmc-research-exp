import logging
import hashlib
import hmac
import re
import uuid

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.participant import Participant

logger = logging.getLogger(__name__)

settings = get_settings()
PROLIFIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{24}$")
PROLIFIC_ID_ERROR = "Please enter a valid Prolific ID. It should contain exactly 24 letters and numbers."


def get_fernet() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.encode())


def normalize_prolific_id(prolific_id: str | None) -> str:
    """Normalize a Prolific participant ID before storage or comparison."""
    return (prolific_id or "").strip()


def is_valid_prolific_id(prolific_id: str | None) -> bool:
    """Return whether a value matches Prolific's 24-character alphanumeric ID format."""
    return bool(PROLIFIC_ID_PATTERN.fullmatch(normalize_prolific_id(prolific_id)))


def hash_prolific_id(prolific_id: str) -> str:
    """Return a deterministic keyed hash for duplicate checks."""
    return hmac.new(
        settings.ENCRYPTION_KEY.encode(),
        normalize_prolific_id(prolific_id).encode(),
        hashlib.sha256,
    ).hexdigest()


def encrypt_prolific_id(prolific_id: str) -> str:
    """Encrypt a Prolific participant ID for storage."""
    return get_fernet().encrypt(normalize_prolific_id(prolific_id).encode()).decode()


def decrypt_prolific_id(encrypted: str) -> str:
    """Decrypt a stored Prolific participant ID."""
    return get_fernet().decrypt(encrypted.encode()).decode()


def sanitize_prolific_id(raw: str | None) -> str:
    """Normalize and discard IDs that do not match Prolific format."""
    prolific_id = normalize_prolific_id(raw)
    if prolific_id and not is_valid_prolific_id(prolific_id):
        return ""
    return prolific_id


def decrypt_prolific_id_safe(encrypted: str | None) -> str:
    """Decrypt a stored Prolific ID, returning empty string on failure."""
    if not encrypted:
        return ""
    try:
        return decrypt_prolific_id(encrypted)
    except Exception:
        return ""


def store_on_participant(participant: Participant, prolific_id: str) -> None:
    """Persist encrypted Prolific ID and lookup hash on a participant."""
    participant.prolific_id_encrypted = encrypt_prolific_id(prolific_id)
    participant.prolific_id_hash = hash_prolific_id(prolific_id)


def is_prolific_unique_violation(exc: BaseException) -> bool:
    """True when a DB error is the unique constraint on Prolific ID columns."""
    text = str(exc).lower()
    orig = getattr(exc, "orig", None)
    if orig is not None:
        text = f"{text} {orig}".lower()
    return "prolific_id_hash" in text or "prolific_id_encrypted" in text


def validate_for_welcome(raw: str | None) -> tuple[str, str | None]:
    """Validate welcome-form Prolific ID. Returns (normalized_id, error_message)."""
    prolific_id = normalize_prolific_id(raw)
    if not prolific_id and not settings.DEMO_MODE:
        return prolific_id, "Please enter your Prolific ID."
    if prolific_id and not is_valid_prolific_id(prolific_id):
        return prolific_id, PROLIFIC_ID_ERROR
    return prolific_id, None


async def find_duplicate_participant(
    db: AsyncSession,
    prolific_id: str,
    *,
    exclude_participant_id: uuid.UUID | None = None,
) -> Participant | None:
    """Find an existing participant with the same Prolific ID."""
    prolific_id = normalize_prolific_id(prolific_id)
    if not prolific_id:
        return None

    query = select(Participant).where(
        Participant.prolific_id_hash == hash_prolific_id(prolific_id)
    )
    if exclude_participant_id:
        query = query.where(Participant.id != exclude_participant_id)

    result = await db.execute(query)
    if existing := result.scalar_one_or_none():
        return existing

    # Backward compatibility for rows created before prolific_id_hash existed.
    legacy_query = select(Participant).where(
        Participant.prolific_id_hash.is_(None),
        Participant.prolific_id_encrypted.is_not(None),
    )
    if exclude_participant_id:
        legacy_query = legacy_query.where(Participant.id != exclude_participant_id)

    legacy_result = await db.execute(legacy_query)
    for legacy_participant in legacy_result.scalars().all():
        legacy_id = sanitize_prolific_id(
            decrypt_prolific_id_safe(legacy_participant.prolific_id_encrypted)
        )
        if legacy_id == prolific_id:
            return legacy_participant

    return None


async def is_duplicate_participant(
    db: AsyncSession,
    prolific_id: str,
    *,
    exclude_participant_id: uuid.UUID | None = None,
) -> bool:
    """Return True when another participant already used this Prolific ID."""
    if settings.DEMO_MODE or not prolific_id:
        return False
    return await find_duplicate_participant(
        db, prolific_id, exclude_participant_id=exclude_participant_id
    ) is not None


async def send_prolific_completion(session_id: str) -> None:
    """Send completion callback to Prolific."""
    import httpx

    url = settings.PROLIFIC_COMPLETION_URL
    if not url:
        logger.warning("PROLIFIC_COMPLETION_URL not configured, skipping callback")
        return

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"session_id": session_id})
            if resp.status_code == 200:
                logger.info(f"Prolific completion sent for session {session_id}")
            else:
                logger.error(f"Prolific completion failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Prolific completion callback error: {e}")
