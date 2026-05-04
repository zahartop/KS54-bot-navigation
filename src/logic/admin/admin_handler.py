from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router, types
from aiogram.filters import Command

from src.config.content import ADMIN_EXPORT_EMPTY, ADMIN_EXPORT_TIMEOUT, ADMIN_NO_ACCESS
from src.logic.admin.admin_service import AdminService, AdminStatusCallback, export_buffered_file
from src.utils.safe_handler import safe_handler

router = Router()
logger = logging.getLogger(__name__)


async def _edit_or_answer(
    callback: types.CallbackQuery,
    text: str,
    keyboard: types.InlineKeyboardMarkup,
) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(Command("admin"))
@safe_handler
async def admin_command(message: types.Message, admin_service: AdminService) -> None:
    if not await admin_service.is_admin(message.from_user.id):
        await message.answer(ADMIN_NO_ACCESS)
        logger.warning("Попытка доступа к /admin: user_id=%s", message.from_user.id)
        return

    logger.info("Открыта админ-панель: user_id=%s", message.from_user.id)
    await message.answer(admin_service.welcome_text(), reply_markup=admin_service.main_menu_markup(), parse_mode="HTML")


@router.callback_query(F.data == "admin_back")
@safe_handler
async def admin_back(callback: types.CallbackQuery, admin_service: AdminService) -> None:
    if not await admin_service.is_admin(callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return
    await _edit_or_answer(callback, admin_service.welcome_text(), admin_service.main_menu_markup())
    await callback.answer()


@router.callback_query(F.data == "admin_stats")
@safe_handler
async def admin_stats(callback: types.CallbackQuery, admin_service: AdminService) -> None:
    if not await admin_service.is_admin(callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return

    text, markup = await admin_service.build_stats_screen()
    await _edit_or_answer(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data == "admin_new_apps")
@safe_handler
async def admin_new_apps(callback: types.CallbackQuery, admin_service: AdminService) -> None:
    if not await admin_service.is_admin(callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return

    text, keyboard = await admin_service.build_new_apps_screen()
    await _edit_or_answer(callback, text, keyboard)
    await callback.answer()


@router.callback_query(AdminStatusCallback.filter())
@safe_handler
async def admin_status_change(
    callback: types.CallbackQuery,
    callback_data: AdminStatusCallback,
    admin_service: AdminService,
) -> None:
    if not await admin_service.is_admin(callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return

    result = await admin_service.apply_application_status(
        app_type=callback_data.app_type,
        app_id=callback_data.app_id,
        status=callback_data.status,
    )

    if not result.success:
        await callback.answer(result.failure_alert or "Ошибка", show_alert=True)
        return

    await callback.answer(result.success_answer or "", show_alert=False)
    logger.info(
        "Статус заявки изменён: type=%s id=%s status=%s admin_id=%s",
        callback_data.app_type,
        callback_data.app_id,
        callback_data.status,
        callback.from_user.id,
    )
    await _edit_or_answer(callback, result.body_text, result.body_markup)


@router.callback_query(F.data == "admin_export")
@safe_handler
async def admin_export(callback: types.CallbackQuery, admin_service: AdminService) -> None:
    if not await admin_service.is_admin(callback.from_user.id):
        await callback.answer(ADMIN_NO_ACCESS, show_alert=True)
        return

    await callback.answer("Генерирую файл...")

    try:
        package = await admin_service.build_export_package()
    except asyncio.TimeoutError:
        await callback.message.answer(ADMIN_EXPORT_TIMEOUT)
        return

    if package is None:
        await callback.message.answer(ADMIN_EXPORT_EMPTY)
        return

    await callback.message.answer_document(
        export_buffered_file(package),
        caption=package.caption,
        parse_mode="HTML",
    )
    logger.info(
        "CSV выгружен: user_id=%s, open_day=%s, specialty=%s",
        callback.from_user.id,
        package.open_day,
        package.specialty,
    )
