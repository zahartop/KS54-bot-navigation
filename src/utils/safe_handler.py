import logging
from functools import wraps
from typing import Any, Awaitable, Callable

from aiogram import types

logger = logging.getLogger(__name__)


def safe_handler(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Защитный декоратор для хендлеров: логирует исключения и не дает боту падать."""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except Exception:
            logger.exception("Необработанная ошибка в хендлере %s", func.__name__)

            event = None
            for arg in args:
                if isinstance(arg, (types.Message, types.CallbackQuery)):
                    event = arg
                    break

            try:
                if isinstance(event, types.CallbackQuery):
                    if event.message:
                        await event.message.answer(
                            "Произошла ошибка, попробуйте снова. Введите /start для возврата в главное меню."
                        )
                    await event.answer()
                elif isinstance(event, types.Message):
                    await event.answer(
                        "Произошла ошибка, попробуйте снова. Введите /start для возврата в главное меню."
                    )
            except Exception:
                logger.exception("Не удалось отправить сообщение об ошибке пользователю")
            return None

    return wrapper
