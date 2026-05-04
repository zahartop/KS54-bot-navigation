"""Общий UI и переходы по согласию на политику ПДн (хендлеры главного меню)."""

from __future__ import annotations

from pathlib import Path

from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile

from src.config.content import (
    CONSENT_TEXT,
    FORM_ASK_FIO,
    OPEN_DAY_DATE_CHOSEN,
)
from src.logic.abi.keyboards.kb import cancel_input_kb, get_consent_kb
from src.logic.abi.states.admission_form import AdmissionForm
from src.utils.ui_utils import safe_edit_text

_POLICY_PATH = Path(__file__).resolve().parents[2] / "policy.pdf"


async def show_consent_screen(callback: types.CallbackQuery) -> None:
    """Сначала текст с кнопками, затем PDF политики (если файл есть в образе/проекте)."""
    if callback.message is None:
        return
    kb = get_consent_kb()
    await callback.message.answer(CONSENT_TEXT, reply_markup=kb, parse_mode="HTML")
    if _POLICY_PATH.exists():
        await callback.message.answer_document(FSInputFile(_POLICY_PATH))


async def send_consent_screen_for_message(
    message: types.Message,
    *,
    reminder_only_text: str | None = None,
) -> None:
    """Отправить политику в чат как ответ на сообщение; при напоминании — только короткий текст."""
    if reminder_only_text:
        await message.answer(reminder_only_text)
        return
    kb = get_consent_kb()
    await message.answer(CONSENT_TEXT, reply_markup=kb, parse_mode="HTML")
    if _POLICY_PATH.exists():
        await message.answer_document(FSInputFile(_POLICY_PATH))


async def enter_open_day_form_after_policy(
    callback: types.CallbackQuery, state: FSMContext, selected_date: str
) -> None:
    await state.update_data(open_day_date=selected_date, next_form="open_day")
    await state.set_state(AdmissionForm.fio)
    await safe_edit_text(
        callback.message,
        OPEN_DAY_DATE_CHOSEN.format(date=selected_date),
        parse_mode="HTML",
    )
    await callback.message.answer(FORM_ASK_FIO, reply_markup=cancel_input_kb(), parse_mode="HTML")
