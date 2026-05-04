"""Совместимость: историческое имя ``AdmissionRepository`` = :class:`UserRepository`.

Новые методы (напр. ``get_all_registered_telegram_user_ids`` для рассылок) см. ``UserRepository``.
"""

from src.data.user_repository import UserRepository as AdmissionRepository

__all__ = ["AdmissionRepository"]
