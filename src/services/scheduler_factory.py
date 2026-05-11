"""Создание APScheduler с персистентным job store в PostgreSQL.

SQLAlchemyJobStore использует **синхронный** драйвер (psycopg2), отдельно от asyncpg бота.
Задачи хранят callable по строке ``module:func`` и примитивные kwargs — без Bot в pickle.
"""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.config.settings import Settings
from src.utils.pii import mask_for_log

logger = logging.getLogger(__name__)


def _sync_sqlalchemy_url(async_url: str) -> str:
    u = async_url.strip()
    if u.startswith("sqlite"):
        return u.replace("sqlite+aiosqlite:", "sqlite:", 1)
    if u.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg2://" + u[len("postgresql+asyncpg://") :]
    if u.startswith("postgresql+psycopg://"):
        return "postgresql+psycopg2://" + u[len("postgresql+psycopg://") :]
    if u.startswith("postgresql://"):
        return "postgresql+psycopg2://" + u[len("postgresql://") :]
    return u


def build_async_scheduler(settings: Settings) -> AsyncIOScheduler:
    """AsyncIOScheduler + PostgreSQL (если URL конвертируется), иначе MemoryJobStore."""

    try:
        sync_url = _sync_sqlalchemy_url(settings.effective_database_url)
        store = SQLAlchemyJobStore(url=sync_url, tablename="apscheduler_jobs")
        sched = AsyncIOScheduler(
            jobstores={"default": store},
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            },
            timezone=ZoneInfo("UTC"),
        )
        logger.info("APScheduler: SQLAlchemyJobStore (PostgreSQL)")
        return sched
    except Exception as exc:
        logger.warning(
            "APScheduler: не удалось подключить SQLAlchemyJobStore (%s), MemoryJobStore",
            mask_for_log(str(exc)),
        )
        return AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            },
            timezone=ZoneInfo("UTC"),
        )
