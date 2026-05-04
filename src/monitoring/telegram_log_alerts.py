"""ERROR/CRITICAL → Telegram админу, с паузами и лимитом сообщений за час."""

from __future__ import annotations

import asyncio
import html
import logging
import time
import traceback
from collections import deque

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError

from src.config.settings import Settings, get_settings
from src.utils.pii import PIIMaskingFilter

_LOG = logging.getLogger(__name__)
_MAIN_LOOP: asyncio.AbstractEventLoop | None = None
_ALERT_QUEUE_MAX = 42
_ALERT_QUEUE_REF: asyncio.Queue[str] | None = None


def set_alert_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _MAIN_LOOP
    _MAIN_LOOP = loop


async def alert_consumer(bot: Bot, queue: asyncio.Queue[str], settings: Settings) -> None:
    min_gap = getattr(settings, "ALERT_TELEGRAM_MIN_INTERVAL_SECONDS", 120)
    max_per_hour = getattr(settings, "ALERT_TELEGRAM_MAX_PER_HOUR", 12)
    hourly_window: deque[float] = deque()
    admin_id = settings.ADMIN_ID
    next_allowed = 0.0

    while True:
        chunk = await queue.get()
        if admin_id <= 0:
            continue

        now = time.monotonic()
        while hourly_window and now - hourly_window[0] > 3600.0:
            hourly_window.popleft()

        if len(hourly_window) >= max_per_hour:
            _LOG.warning("Алерты TG: часовой лимит достигнут, сообщение дропнуто")
            continue

        if now < next_allowed:
            await asyncio.sleep(next_allowed - now)

        try:
            await bot.send_message(admin_id, chunk[:4096], parse_mode="HTML")
        except Exception:
            _LOG.debug("Не удалось отправить лог-алерт админу")

        now2 = time.monotonic()
        hourly_window.append(now2)
        next_allowed = now2 + float(min_gap)


def start_alert_consumer_task(bot: Bot) -> asyncio.Task:
    global _ALERT_QUEUE_REF

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_ALERT_QUEUE_MAX)
    _ALERT_QUEUE_REF = queue
    settings = get_settings()
    return asyncio.create_task(alert_consumer(bot, queue, settings), name="telegram_log_alerts")


def _schedule_plain_html(text_html: str) -> None:
    if _MAIN_LOOP is None or not _MAIN_LOOP.is_running() or _ALERT_QUEUE_REF is None:
        return
    fut = asyncio.run_coroutine_threadsafe(_safe_put_alert(text_html), _MAIN_LOOP)

    def _silent_cb(f):  # type: ignore[no-untyped-def]
        exc = f.exception()
        if exc:
            _LOG.debug("enqueue alert fut: %s", exc)

    fut.add_done_callback(_silent_cb)


async def _safe_put_alert(html_text: str) -> None:
    q = _ALERT_QUEUE_REF
    if q is None:
        return
    try:
        q.put_nowait(html_text)
    except asyncio.QueueFull:
        _LOG.warning("Алерты: очередь переполнена, дроп")


class SkipTransientNetworkTelegramAlertFilter(logging.Filter):
    """Не дублировать в Telegram алерты по сетевым сбоям и таймаутам (в файл/консоль запись остаётся)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "skip_admin_telegram", False):
            return False
        exc_info = record.exc_info
        if exc_info and exc_info[1] is not None:
            err = exc_info[1]
            if isinstance(err, (TelegramNetworkError, asyncio.TimeoutError)):
                return False
        return True


class AdminTelegramLogHandler(logging.Handler):
    def __init__(self, level: int = logging.ERROR) -> None:
        super().__init__(level=level)
        self.addFilter(_SkipSelfLoggerFilter())
        self.addFilter(SkipTransientNetworkTelegramAlertFilter())
        self.addFilter(PIIMaskingFilter())

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR:
            return
        if _MAIN_LOOP is None or _ALERT_QUEUE_REF is None:
            return
        try:
            text_html = format_log_record_as_alert_html(record)
            _schedule_plain_html(text_html)
        except Exception:
            self.handleError(record)


def format_log_record_as_alert_html(record: logging.LogRecord) -> str:
    pieces = [
        "🚨 " + html.escape(record.levelname),
        "<code>" + html.escape(record.name) + "</code>",
        "",
        html.escape(str(record.getMessage()))[:2600],
    ]
    parts = "\n".join(pieces)
    if record.exc_info:
        try:
            tb = "".join(
                traceback.format_exception(
                    record.exc_info[0],
                    record.exc_info[1],
                    record.exc_info[2],
                )
            )
            tail = tb[-900:]
            parts += "\n\n<pre>" + html.escape(tail) + "</pre>"
        except Exception:
            logging.getLogger(__name__).warning(
                "format_log_record_as_alert_html: не удалось добавить traceback.", exc_info=True
            )
    max_c = getattr(get_settings(), "ALERT_TELEGRAM_MAX_BODY_CHARS", 3500)
    if len(parts) > max_c:
        return parts[: max_c - 30] + "…"
    return parts


class _SkipSelfLoggerFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("src.monitoring.telegram_log_alerts")


def attach_admin_telegram_log_handler() -> AdminTelegramLogHandler:
    h = AdminTelegramLogHandler()
    logging.getLogger().addHandler(h)
    return h
