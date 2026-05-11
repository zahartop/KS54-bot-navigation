"""Тесты базовых команд /start и /help."""

from __future__ import annotations

from unittest.mock import AsyncMock

from aiogram.fsm.context import FSMContext
from src.config.content import HELP_MESSAGE, WELCOME_MESSAGE
from src.logic.abi.main_menu_handler import cmd_help, cmd_start
from src.utils.keyboards import KeyboardFactory


async def test_cmd_start(mock_message: AsyncMock, state: FSMContext):
    await cmd_start(mock_message, state)

    mock_message.answer.assert_called_once_with(
        WELCOME_MESSAGE,
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        parse_mode="HTML",
    )
    current_state = await state.get_state()
    assert current_state is None


async def test_cmd_help(mock_message: AsyncMock):
    await cmd_help(mock_message)

    mock_message.answer.assert_called_once_with(
        HELP_MESSAGE,
        parse_mode="HTML",
    )
