"""Liveness-проверки Postgres и Telegram (чистые функции без HTTP)."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from src.config.settings import get_settings
from src.data.database import db_manager

logger = logging.getLogger(__name__)


async def check_database_ok() -> tuple[bool, str | None]:
    try:
        ms = await db_manager.measure_select_one_ms()
        return True, f"ok latency_ms≈{ms:.1f}"
    except Exception as exc:
        logger.debug("health db fail: %s", exc)
        return False, str(exc)[:200]


async def check_telegram_ok(bot: Bot) -> tuple[bool, str | None]:
    try:
        timeout_s = float(max(30.0, get_settings().TELEGRAM_HTTP_TIMEOUT_SECONDS))
        me = await bot.get_me(request_timeout=int(timeout_s))
        return True, f"@{me.username}" if me.username else str(me.id)
    except Exception as exc:
        logger.debug("health telegram fail: %s", exc)
        return False, str(exc)[:200]


async def assert_startup_health(bot: Bot) -> None:
    """Перед опросом: PostgreSQL и сессия Telegram (get_me). При сбое — исключение."""

    settings = get_settings()
    pg_ok, pg_detail = await check_database_ok()
    if not pg_ok:
        raise RuntimeError(f"Startup health: PostgreSQL недоступен: {pg_detail}")

    max_attempts = int(settings.TELEGRAM_STARTUP_MAX_ATTEMPTS)
    base_delay = float(settings.TELEGRAM_STARTUP_BACKOFF_INITIAL_SECONDS)
    max_delay = float(settings.TELEGRAM_STARTUP_BACKOFF_MAX_SECONDS)

    last_detail: str | None = None
    for attempt in range(1, max_attempts + 1):
        tg_ok, tg_detail = await check_telegram_ok(bot)
        if tg_ok:
            logger.info("Startup health OK: postgres=%s; telegram=%s", pg_detail, tg_detail)
            return
        last_detail = tg_detail
        logger.warning(
            "Startup health: Telegram get_me неуспешно (попытка %s/%s): %s",
            attempt,
            max_attempts,
            tg_detail,
        )
        if attempt < max_attempts:
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            await asyncio.sleep(delay)

    raise RuntimeError(f"Startup health: сессия бота (Telegram API) недоступна: {last_detail}")
