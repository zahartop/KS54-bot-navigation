"""Периодический watchdog: latency БД и счётчик ретраев записей."""

from __future__ import annotations

import logging

from aiogram import Bot

from src.config.settings import get_settings
from src.data.database import db_manager
from src.monitoring import metrics as mon_metrics
from src.utils.telegram_session import create_bot_aiohttp_session

_LOG = logging.getLogger(__name__)


async def run_health_watchdog() -> None:
    """APScheduler строка ``src.monitoring.watchdog_job:run_health_watchdog``."""

    settings = get_settings()
    aid = settings.ADMIN_ID

    hist, baseline = mon_metrics.previous_median_before_append()
    retries_bucket = mon_metrics.take_write_retries_and_reset()

    latency_ms: float
    issues: list[str] = []

    try:
        latency_ms = await db_manager.measure_select_one_ms()
    except Exception as exc:
        latency_ms = -1.0
        await _tg_warn_plain(f"⚠️ Watchdog: SELECT 1 не выполнен ({type(exc).__name__})\n{str(exc)[:480]}")

    threshold = getattr(settings, "WATCHDOG_DB_LATENCY_WARN_MS", 800)
    ratio = getattr(settings, "WATCHDOG_DB_LATENCY_SPIKE_RATIO", 2.5)

    if latency_ms >= 0:
        mon_metrics.record_watchdog_ping_ms(latency_ms)

        slow_plain = latency_ms >= threshold
        spike_vs_history = baseline is not None and len(hist) >= 2 and latency_ms >= baseline * ratio
        if slow_plain or spike_vs_history:
            issues.append(
                f"⚠️ Лаг БД SELECT 1: <b>{latency_ms:.0f} мс</b> "
                f"(warn ≥{threshold:g} мс; ×{ratio} к медиане ~{baseline or 0:.0f})\n",
            )

    rlim = getattr(settings, "WATCHDOG_WRITE_RETRIES_WARN_PER_HOUR", 25)
    if retries_bucket >= rlim:
        issues.append(f"⚠️ Много ретраев записи с прошлой проверки: <b>{retries_bucket}</b> (порог {rlim})\n")

    if not issues:
        _LOG.debug("Watchdog: latency=%sms retries_delta=%s", latency_ms, retries_bucket)
        return

    if aid <= 0:
        _LOG.warning("Watchdog issues but ADMIN_ID=0: %s", "; ".join(i[:80] for i in issues))
        return

    text = "<b>College Bot — мониторинг</b>\n\n" + "".join(issues)

    bot = Bot(token=settings.BOT_TOKEN.get_secret_value().strip(), session=create_bot_aiohttp_session(settings))
    try:
        await bot.send_message(aid, text[:3900], parse_mode="HTML")
    except Exception:
        _LOG.warning("Watchdog: отправка сводки админу в Telegram не удалась.", exc_info=True)
    finally:
        await bot.session.close()


async def _tg_warn_plain(text_plain: str) -> None:
    settings = get_settings()
    if settings.ADMIN_ID <= 0:
        return

    bot = Bot(token=settings.BOT_TOKEN.get_secret_value().strip(), session=create_bot_aiohttp_session(settings))
    try:
        await bot.send_message(settings.ADMIN_ID, text_plain[:4000])
    except Exception:
        _LOG.warning("Watchdog: не удалось отправить предупреждение админу в Telegram.", exc_info=True)
    finally:
        await bot.session.close()
