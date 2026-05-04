"""Проверка прав администратора: ``telegram_users.is_admin`` либо совпадение с ``ADMIN_ID`` в .env."""

from __future__ import annotations

from src.config.settings import get_settings
from src.data.user_repository import UserRepository


async def user_is_bot_admin(telegram_user_id: int, user_repository: UserRepository) -> bool:
    aid = get_settings().ADMIN_ID
    if aid > 0 and int(telegram_user_id) == int(aid):
        return True
    return await user_repository.is_telegram_user_admin(telegram_user_id)
