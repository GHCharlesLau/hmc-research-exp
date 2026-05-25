import logging
from cryptography.fernet import Fernet

from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


def get_fernet() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt_prolific_id(prolific_id: str) -> str:
    """Encrypt a Prolific participant ID for storage."""
    return get_fernet().encrypt(prolific_id.encode()).decode()


def decrypt_prolific_id(encrypted: str) -> str:
    """Decrypt a stored Prolific participant ID."""
    return get_fernet().decrypt(encrypted.encode()).decode()


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
