from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    SECRET_KEY: str = "change-me"
    DEBUG: bool = False

    # Database
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
