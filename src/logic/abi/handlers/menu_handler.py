"""Хендлеры главного меню: /start, /help, /about, навигация разделов."""

from __future__ import annotations

import logging
import random

from aiogram import Bot, F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext

from src.application.schemas.enrollment_events import EnrollmentEvent
from src.config.content import (
    ABOUT_MESSAGE,
    APPEAL_ACCEPTED,
    APPEAL_ASK_TEXT,
    BACK_TO_MENU_MESSAGE,
    CANCEL_MESSAGE,
    HELP_MESSAGE,
    PERSONAL_CABINET_STUB,
    PLACEHOLDER_SECTIONS,
    SECTION_NOT_FOUND,
    WELCOME_MESSAGE,
)
from src.data.user_repository import UserRepository
from src.infrastructure.kafka_enrollment import get_kafka_producer
from src.logic.abi.keyboards.kb import appeal_cancel_kb
from src.logic.abi.states.admission_form import AppealForm
from src.utils.keyboards import KeyboardFactory
from src.utils.safe_handler import safe_handler
from src.utils.ui_utils import safe_edit_text

router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
@safe_handler
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    logger.info("Пользователь открыл главное меню: user_id=%s", message.from_user.id)
    await message.answer(
        WELCOME_MESSAGE,
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("help"))
@safe_handler
async def cmd_help(message: types.Message):
    await message.answer(HELP_MESSAGE, parse_mode="HTML")


@router.message(Command("about"))
@safe_handler
async def cmd_about(message: types.Message):
    await message.answer(ABOUT_MESSAGE, parse_mode="HTML")


@router.callback_query(F.data == "main_menu")
@safe_handler
async def back_to_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_text(
        callback.message,
        BACK_TO_MENU_MESSAGE,
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_input")
@safe_handler
async def cancel_input(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_text(
        callback.message,
        CANCEL_MESSAGE,
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "personal_cabinet")
@safe_handler
async def personal_cabinet(callback: types.CallbackQuery):
    await callback.answer("Загружаю...")
    await safe_edit_text(
        callback.message,
        PERSONAL_CABINET_STUB,
        reply_markup=KeyboardFactory.create_submenu_keyboard("personal_cabinet"),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "compose_appeal")
@safe_handler
async def compose_appeal(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Загружаю...")
    await state.set_state(AppealForm.waiting_text)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        APPEAL_ASK_TEXT,
        reply_markup=appeal_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AppealForm.waiting_text)
@safe_handler
async def process_appeal_text(
    message: types.Message,
    state: FSMContext,
    bot: Bot,
    user_repository: UserRepository,
):
    text = message.text
    if not text or not text.strip():
        await message.answer("Пожалуйста, введите текст обращения.", reply_markup=appeal_cancel_kb())
        return

    appeal_id = random.randint(100000, 999999)  # noqa: S311
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name or ""

    admin_text = (
        "#Обращение\n\n"
        f"<b>ID обращения:</b> <code>{appeal_id}</code>\n"
        f"<b>От:</b> {full_name} (@{username}, id: {user_id})\n\n"
        f"<b>Текст:</b>\n{text.strip()}"
    )
    admin_ids = await user_repository.get_admin_telegram_user_ids()
    for admin_tid in admin_ids:
        try:
            await bot.send_message(admin_tid, admin_text, parse_mode="HTML")
        except Exception:
            logger.warning("Не удалось отправить обращение админу: %s", admin_tid)

    kp = get_kafka_producer()
    if kp is not None:
        await kp.publish_enrollment(
            EnrollmentEvent(
                user_id=user_id,
                event_type="appeal_submitted",
                payload={
                    "appeal_id": appeal_id,
                    "text_preview": text.strip()[:500],
                    "username": username,
                    "full_name": full_name,
                },
            )
        )

    await state.clear()
    await message.answer(
        APPEAL_ACCEPTED.format(appeal_id=appeal_id),
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query()
@safe_handler
async def handle_menu_navigation(callback: types.CallbackQuery, state: FSMContext):
    menu_id = callback.data
    section_text = PLACEHOLDER_SECTIONS.get(menu_id)

    if not section_text:
        await callback.answer(SECTION_NOT_FOUND, show_alert=True)
        return

    await callback.answer("Загружаю...")

    if menu_id == "about_college":
        kb = KeyboardFactory.create_about_submenu_keyboard()
    elif menu_id == "contact_us":
        kb = KeyboardFactory.create_contacts_submenu_keyboard()
    else:
        kb = KeyboardFactory.create_submenu_keyboard(menu_id)

    await safe_edit_text(callback.message, section_text, reply_markup=kb, parse_mode="HTML")
