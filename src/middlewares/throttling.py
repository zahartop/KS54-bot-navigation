import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject
from cachetools import TTLCache  # нужно установить: pip install cachetools

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, ttl=0.5):
        self.cache = TTLCache(maxsize=10000, ttl=ttl)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user and user.id in self.cache:
            logger.warning("Throttling triggered: user_id=%s", user.id)
            # Чтобы у пользователя не зависал интерфейс на inline-кнопках,
            # обязательно отвечаем на callback_query, даже если игнорируем обработку.
            try:
                if isinstance(event, CallbackQuery):
                    await event.answer()
            except Exception:
                logger.warning("Throttling: не удалось ответить на callback_query.", exc_info=True)
            return  # Игнорируем запрос, если он пришел чаще чем ttl

        if user:
            self.cache[user.id] = True
        return await handler(event, data)
