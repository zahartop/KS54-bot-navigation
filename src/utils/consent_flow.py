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
    SAVED_PROFILE_PROMPT,
)
from src.data.user_repository import UserRepository
from src.logic.abi.keyboards.kb import cancel_input_kb, get_consent_kb, saved_profile_kb
from src.logic.abi.states.admission_form import AdmissionForm
from src.utils.ui_utils import safe_edit_text

_POLICY_PATH = Path(__file__).resolve().parents[2] / "policy.pdf"


async def show_consent_screen(callback: types.CallbackQuery, state: FSMContext | None = None) -> None:
    """Сначала текст с кнопками, затем PDF политики (если файл есть в образе/проекте)."""
    if callback.message is None:
        return
    kb = get_consent_kb()
    await callback.message.answer(CONSENT_TEXT, reply_markup=kb, parse_mode="HTML")
    if _POLICY_PATH.exists():
        doc_msg = await callback.message.answer_document(FSInputFile(_POLICY_PATH))
        if state:
            await state.update_data(_policy_doc_msg_id=doc_msg.message_id)


async def send_consent_screen_for_message(
    message: types.Message,
    *,
    reminder_only_text: str | None = None,
    state: FSMContext | None = None,
) -> None:
    """Отправить политику в чат как ответ на сообщение; при напоминании — только короткий текст."""
    if reminder_only_text:
        await message.answer(reminder_only_text)
        return
    kb = get_consent_kb()
    await message.answer(CONSENT_TEXT, reply_markup=kb, parse_mode="HTML")
    if _POLICY_PATH.exists():
        doc_msg = await message.answer_document(FSInputFile(_POLICY_PATH))
        if state:
            await state.update_data(_policy_doc_msg_id=doc_msg.message_id)


async def enter_open_day_form_after_policy(
    callback: types.CallbackQuery,
    state: FSMContext,
    selected_date: str,
    user_repository: UserRepository | None = None,
) -> None:
    await state.update_data(open_day_date=selected_date, next_form="open_day")
    await safe_edit_text(
        callback.message,
        OPEN_DAY_DATE_CHOSEN.format(date=selected_date),
        parse_mode="HTML",
    )

    saved = None
    if user_repository and callback.from_user:
        saved = await user_repository.get_saved_profile(callback.from_user.id)

    if saved:
        await state.set_state(AdmissionForm.saved_profile_choice)
        await callback.message.answer(
            SAVED_PROFILE_PROMPT.format(fio=saved["fio"], phone=saved["phone"], email=saved["email"]),
            reply_markup=saved_profile_kb(saved["fio"]),
            parse_mode="HTML",
        )
    else:
        await state.set_state(AdmissionForm.fio)
        await callback.message.answer(FORM_ASK_FIO, reply_markup=cancel_input_kb(), parse_mode="HTML")
