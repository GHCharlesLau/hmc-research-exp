"""Alembic environment. Uses sync psycopg2 so Render's sslmode=require URLs work."""

import os
from logging.config import fileConfig
from urllib.parse import urlparse

from sqlalchemy import engine_from_config, pool
from alembic import context

from config import _convert_db_url
from database import Base
from models import (  # noqa: F401
    Participant, ChatRoom, ChatMessage, SurveyResponse,
    ExperimentConfig, ExperimentSession,
)

config = context.config


def _redacted_db_location(url: str) -> str:
    """Host/db only, for error messages. Never includes user/password."""
    normalized = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    normalized = normalized.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    host = parsed.hostname or "(no-host)"
    port = parsed.port or 5432
    db = (parsed.path or "/").lstrip("/") or "(no-db)"
    return f"{host}:{port}/{db}"


db_url = os.environ.get("DATABASE_URL", "")
if db_url:
    db_url = _convert_db_url(db_url, "psycopg2")
    # ConfigParser interpolates %; Render passwords are often percent-encoded.
    config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with a sync engine."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    except OSError as exc:
        location = _redacted_db_location(db_url or config.get_main_option("sqlalchemy.url") or "")
        raise ConnectionError(
            f"Cannot reach Postgres at {location}. On Render, set DATABASE_URL to the "
            "Postgres service's Internal Connection String (same region as this web "
            "service), and confirm the database is running (not an expired free instance)."
        ) from exc


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
