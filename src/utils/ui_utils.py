from __future__ import annotations

import logging
from typing import Any, Optional

from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)

_PREV_MSG_KEY = "_prev_bot_msg_id"


async def delete_prev_message(bot: Bot, chat_id: int, state: FSMContext) -> None:
    """Remove the previous bot prompt tracked in FSM state."""
    data = await state.get_data()
    prev_id = data.get(_PREV_MSG_KEY)
    if prev_id:
        try:
            await bot.delete_message(chat_id, prev_id)
        except TelegramBadRequest:
            pass
        except Exception:
            logger.debug("delete_prev_message: не удалось удалить msg_id=%s", prev_id)
        await state.update_data(**{_PREV_MSG_KEY: None})


async def track_message(sent: types.Message, state: FSMContext) -> types.Message:
    """Save the sent message ID so it can be cleaned up later."""
    await state.update_data(**{_PREV_MSG_KEY: sent.message_id})
    return sent


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
