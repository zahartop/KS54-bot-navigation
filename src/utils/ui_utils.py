from __future__ import annotations

from typing import Any, Optional

from aiogram import types
from aiogram.exceptions import TelegramBadRequest


async def safe_edit_text(
    message: Optional[types.Message],
    text: str,
    *,
    reply_markup: Optional[types.InlineKeyboardMarkup] = None,
    **kwargs: Any,
) -> None:
    """
    Безопасная обертка над Message.edit_text(...).
    Глотает только «message is not modified», чтобы спам кнопок не создавал стектрейсы.
    """
    if not message:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
