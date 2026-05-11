"""Сброс админских FSM-состояний, если у пользователя сняли is_admin (или сессия устарела)."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.data.user_repository import UserRepository
from src.logic.admin.states.broadcast import BroadcastForm

logger = logging.getLogger(__name__)

_ACCESS_DENIED_TEXT = "Доступ ограничен"

_PROTECTED_FSM_STATES: frozenset[str] = frozenset(
    {
        BroadcastForm.composing.state,
        BroadcastForm.preview.state,
    }
)


class AccessControlMiddleware(BaseMiddleware):
    """Если FSM в админской рассылке, а пользователь не админ — clear + сообщение, без вызова хендлеров."""

    def __init__(self, user_repository: UserRepository) -> None:
        self._user_repository = user_repository

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state: FSMContext | None = data.get("state")
        user = data.get("event_from_user")
        if state is None or user is None:
            return await handler(event, data)

        current = await state.get_state()
        if current is None or current not in _PROTECTED_FSM_STATES:
            return await handler(event, data)

        if await self._user_repository.is_telegram_user_admin(user.id):
            return await handler(event, data)

        await state.clear()
        bot: Bot = data["bot"]
        try:
            if isinstance(event, CallbackQuery):
                if event.message:
                    await event.message.answer(_ACCESS_DENIED_TEXT)
                else:
                    await bot.send_message(chat_id=user.id, text=_ACCESS_DENIED_TEXT)
                await event.answer()
            elif isinstance(event, Message):
                await event.answer(_ACCESS_DENIED_TEXT)
            else:
                await bot.send_message(chat_id=user.id, text=_ACCESS_DENIED_TEXT)
        except Exception:
            logger.exception("AccessControl: не удалось отправить уведомление user_id=%s", user.id)
        # Не вызываем handler — эквивалент остановки цепочки без CancelHandler (совместимо с aiogram 3).
        return None

