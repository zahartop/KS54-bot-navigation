"""Фоновая рассылка с учётом лимитов Telegram (не блокирует event loop: sleep с yield)."""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

logger = logging.getLogger(__name__)


def safe_send_interval_seconds(max_messages_per_second: float) -> float:
    """Пауза между сообщениями: не быстрее заданной скорости, но не суше ~1/35 с."""

    rate = float(max_messages_per_second) if max_messages_per_second > 0 else 20.0
    return max(1.0 / min(rate, 30.0), 1.0 / 35.0)


async def run_broadcast_campaign(
    bot: Bot,
    *,
    recipient_ids: Sequence[int],
    text: str | None,
    photo_file_id: str | None,
    max_messages_per_second: float,
) -> tuple[int, int]:
    """Отправляет рассылку последовательно с задержкой. Возвращает (ок, ошибки).

    Вызывается из ``asyncio.create_task`` из хэндлера — не блокирует опрос апдейтов
    других пользователей, т.к. ``await asyncio.sleep`` отдаёт управление циклу.
    """

    delay = safe_send_interval_seconds(max_messages_per_second)
    ok = fail = 0
    for uid in recipient_ids:
        try:
            if photo_file_id:
                cap = text.strip() if text else None
                kwargs: dict = {"chat_id": uid, "photo": photo_file_id}
                if cap:
                    kwargs["caption"] = cap
                    kwargs["parse_mode"] = "HTML"
                await bot.send_photo(**kwargs)
            else:
                if not text:
                    fail += 1
                    await asyncio.sleep(delay)
                    continue
                await bot.send_message(uid, text, parse_mode="HTML")
            ok += 1
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            logger.warning("Broadcast skip user_id=%s: %s", uid, exc)
            fail += 1
        except Exception:
            logger.exception("Broadcast error user_id=%s", uid)
            fail += 1
        await asyncio.sleep(delay)

    return ok, fail
