"""Хендлеры главного меню: /start, /help, /about, навигация разделов."""

from __future__ import annotations

import logging

from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext

from src.config.content import (
    ABOUT_MESSAGE,
    BACK_TO_MENU_MESSAGE,
    CANCEL_MESSAGE,
    HELP_MESSAGE,
    PLACEHOLDER_SECTIONS,
    SECTION_NOT_FOUND,
    WELCOME_MESSAGE,
)
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


@router.callback_query()
@safe_handler
async def handle_menu_navigation(callback: types.CallbackQuery, state: FSMContext):
    menu_id = callback.data
    section_text = PLACEHOLDER_SECTIONS.get(menu_id)

    if section_text:
        await safe_edit_text(
            callback.message,
            section_text,
            reply_markup=KeyboardFactory.create_submenu_keyboard("placeholder"),
            parse_mode="HTML",
        )
    else:
        await callback.answer(SECTION_NOT_FOUND, show_alert=True)
        return

    await callback.answer()
