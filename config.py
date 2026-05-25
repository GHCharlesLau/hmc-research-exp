import os
from pydantic_settings import BaseSettings
from functools import lru_cache


def _convert_db_url(url: str, driver: str) -> str:
    """Convert a postgresql:// URL to use the specified async/sync driver.

    Render provides ``postgresql://user:pass@host:port/db``.
    We need ``postgresql+asyncpg://`` for async and ``postgresql+psycopg2://`` for sync (Alembic).
    """
    if not url:
        return url
    # Replace any existing postgresql+driver:// prefix with plain postgresql:// first
    if url.startswith("postgresql+"):
        url = "postgresql://" + url.split("://", 1)[1]
    # Now add the requested driver
    return url.replace("postgresql://", f"postgresql+{driver}://", 1)


class Settings(BaseSettings):
    # App
    SECRET_KEY: str = "change-me"
    DEBUG: bool = False

    # Database — raw URL (may come from Render as postgresql://)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/conexperiment"
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/conexperiment"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM (primary)
    OPENAI_API_KEY: str = ""
    N1N_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    DEFAULT_MODEL: str = "gpt-4o-mini"
    LLM_TEMPERATURE: float = 0.4
    LLM_TIMEOUT: int = 20
    LLM_MAX_CONCURRENT: int = 30
    LLM_API_BASE: str = ""  # Custom API base URL for primary (e.g. gateway). Empty = use litellm default.

    # LLM (backup / fallback provider)
    LLM_BACKUP_API_BASE: str = ""
    LLM_BACKUP_API_KEY: str = ""
    LLM_BACKUP_MODEL: str = "gpt-4o-mini"

    # Chat controls
    MIN_TURNS: int = 5
    MAX_TURNS: int = 15
    MAX_DURATION: int = 600  # seconds
    HHC_TIMEOUT: int = 120  # seconds

    # Demo mode (for testing and presentations)
    DEMO_MODE: bool = False
    DEMO_MIN_TURNS: int = 2
    DEMO_MAX_TURNS: int = 5
    DEMO_MAX_DURATION: int = 300  # seconds (5min for testing)
    DEMO_HHC_TIMEOUT: int = 10  # seconds

    # Encryption
    ENCRYPTION_KEY: str = ""

    # Admin
    ADMIN_PASSWORD_HASH: str = ""

    # Prolific
    PROLIFIC_COMPLETION_URL: str = ""
    PROLIFIC_API_TOKEN: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def async_database_url(self) -> str:
        """DATABASE_URL guaranteed to use asyncpg driver."""
        return _convert_db_url(self.DATABASE_URL, "asyncpg")

    @property
    def sync_database_url(self) -> str:
        """DATABASE_URL guaranteed to use psycopg2 driver (for Alembic)."""
        # If DATABASE_URL_SYNC is explicitly set, convert it; otherwise derive from DATABASE_URL
        raw = self.DATABASE_URL_SYNC or self.DATABASE_URL
        return _convert_db_url(raw, "psycopg2")


@lru_cache
def get_settings() -> Settings:
    return Settings()
