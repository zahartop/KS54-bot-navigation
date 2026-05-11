"""Alembic environment configuration with async SQLAlchemy support."""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import quote_plus

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Project root must be in sys.path so we can import src.*
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.settings import Settings, get_settings  # noqa: E402
from src.data.models import Base  # noqa: E402

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = Base.metadata


def _docker_migration_database_url(settings: Settings) -> str:
    """URL для миграций внутри контейнера Compose.

    Не используем ``DATABASE_URL`` из ``.env``: часто там ``localhost`` или ``127.0.0.1``
    для запуска Alembic на Mac — внутри контейнера это другой хост и даёт ошибки DNS/коннекта.

    Берём те же ``POSTGRES_*``, что и сервис ``db`` в ``docker-compose.yml``, хост по умолчанию
    ``db``. Переопределение: ``POSTGRES_HOST``, ``POSTGRES_PORT``.
    """
    host = os.environ.get("POSTGRES_HOST", "db")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = quote_plus(settings.POSTGRES_USER)
    password = quote_plus(settings.POSTGRES_PASSWORD.get_secret_value())
    db = quote_plus(settings.POSTGRES_DB)
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


def _migration_database_url(raw: str) -> str:
    """На хосте подставить ``127.0.0.1`` вместо имени сервиса ``db`` из Compose."""
    if os.environ.get("ALEMBIC_KEEP_DB_HOST") == "1":
        return raw
    if "@db:" in raw:
        return raw.replace("@db:", "@127.0.0.1:", 1)
    return raw


def _get_url() -> str:
    """Строка подключения для Alembic (контейнер vs ноутбук)."""
    override = os.environ.get("ALEMBIC_DATABASE_URL", "").strip()
    if override:
        return override

    settings = get_settings()

    if Path("/.dockerenv").exists():
        return _docker_migration_database_url(settings)

    return _migration_database_url(settings.effective_database_url)


# ─── Offline mode ────────────────────────────────────────────────────────────
# Used by: `alembic upgrade --sql`
# Does NOT require a running database; emits raw SQL to stdout.


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ─── Online (async) mode ─────────────────────────────────────────────────────
# Used by: `alembic upgrade head`, `alembic revision --autogenerate`
# Requires a running PostgreSQL instance.


def _do_run_migrations(connection: Connection) -> None:
    is_sqlite = connection.dialect.name == "sqlite"
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=is_sqlite,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(url: str) -> None:
    """SQLite и другие синхронные драйверы."""
    sync_url = url.replace("sqlite+aiosqlite:", "sqlite:", 1)
    engine = create_engine(sync_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        _do_run_migrations(connection)
    engine.dispose()


async def _run_async_migrations(url: str) -> None:
    section = alembic_config.get_section(alembic_config.config_ini_section, {})
    section["sqlalchemy.url"] = url

    engine = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    url = _get_url()
    if url.startswith("sqlite"):
        _run_sync_migrations(url)
    else:
        asyncio.run(_run_async_migrations(url))


# ─── Entry point ─────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
