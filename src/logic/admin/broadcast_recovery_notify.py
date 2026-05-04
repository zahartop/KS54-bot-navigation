"""Уведомления админам о незавершённых рассылках после рестарта бота."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config.content import (
    BROADCAST_RECOVERY_BTN_CANCEL,
    BROADCAST_RECOVERY_BTN_CONTINUE,
    BROADCAST_RECOVERY_STARTUP,
)
from src.data.user_repository import UserRepository

logger = logging.getLogger(__name__)


def _recovery_keyboard(job_id: int) -> Any:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(
            text=BROADCAST_RECOVERY_BTN_CONTINUE,
            callback_data=f"recovery_bc:{job_id}",
        ),
        InlineKeyboardButton(
            text=BROADCAST_RECOVERY_BTN_CANCEL,
            callback_data=f"recovery_bc_cancel:{job_id}",
        ),
    )
    return b.as_markup()


async def notify_pending_broadcast_jobs(bot: Bot, user_repository: UserRepository) -> None:
    jobs = await user_repository.list_resumable_broadcast_recovery_jobs()
    for job in jobs:
        admin_chat = int(job["admin_chat_id"])
        text = BROADCAST_RECOVERY_STARTUP.format(
            job_id=job["id"],
            status=job["status"],
            n=job["recipient_count_snap"],
        )
        try:
            await bot.send_message(admin_chat, text, parse_mode="HTML", reply_markup=_recovery_keyboard(job["id"]))
        except Exception:
            logger.exception("Не удалось отправить уведомление recovery рассылки job_id=%s", job["id"])
