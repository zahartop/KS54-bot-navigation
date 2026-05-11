"""Хендлеры согласия на ПДн и восстановление сохранённого профиля."""

from __future__ import annotations

import logging

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from src.config.content import (
    CONSENT_ERROR,
    CONSENT_REJECTED,
    FORM_ASK_FIO,
    FORM_ASK_FIO_SPECIALTY,
    FORM_DB_TECHNICAL_ERROR,
    NEXT_FORM_AFTER_CONSENT_BROWSE,
    SURVEY_ASK_REGION,
    WELCOME_MESSAGE,
)
from src.data.user_repository import UserRepository
from src.logic.abi.keyboards.kb import cancel_input_kb, specialty_confirm_kb
from src.logic.abi.keyboards.survey_kb import region_kb
from src.logic.abi.states.admission_form import (
    AdmissionForm,
    ConsentState,
    SpecialtyRequestForm,
    SurveyState,
)
from src.utils.consent_flow import enter_open_day_form_after_policy
from src.utils.keyboards import KeyboardFactory
from src.utils.safe_handler import safe_handler
from src.utils.ui_utils import safe_edit_text

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "consent_accept", ConsentState.waiting)
@safe_handler
async def consent_accept(
    callback: types.CallbackQuery,
    state: FSMContext,
    user_repository: UserRepository,
):
    data = await state.get_data()
    next_form = data.get("next_form")
    user_id = callback.from_user.id
    logger.info("Согласие на ПДн получено: user_id=%s, form=%s", user_id, next_form)

    if not await user_repository.mark_policy_accepted(user_id):
        await callback.message.answer(
            FORM_DB_TECHNICAL_ERROR,
            reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        )
        await callback.answer()
        return

    if next_form == "open_day":
        open_day_date = data.get("open_day_date")
        if not open_day_date:
            await state.clear()
            await callback.message.answer(
                CONSENT_ERROR,
                reply_markup=KeyboardFactory.create_main_menu_keyboard(),
            )
            await callback.answer()
            return
        await enter_open_day_form_after_policy(callback, state, str(open_day_date), user_repository)
    elif next_form == NEXT_FORM_AFTER_CONSENT_BROWSE:
        try:
            await callback.message.delete()
        except Exception:
            logger.info("Согласие: не удалось удалить сообщение с экраном политики.", exc_info=True)
        await state.clear()
        await callback.message.answer(
            WELCOME_MESSAGE,
            reply_markup=KeyboardFactory.create_main_menu_keyboard(),
            parse_mode="HTML",
        )
    elif next_form == "specialty":
        try:
            await callback.message.delete()
        except Exception:
            logger.info("Согласие (специальность): не удалось удалить сообщение.", exc_info=True)
        await state.update_data(next_form="specialty")
        await state.set_state(SurveyState.region)
        await callback.message.answer(SURVEY_ASK_REGION, reply_markup=region_kb())
    else:
        await state.clear()
        await callback.message.answer(
            CONSENT_ERROR,
            reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data == "consent_reject", ConsentState.waiting)
@safe_handler
async def consent_reject(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    logger.info("Согласие на ПДн отклонено: user_id=%s", callback.from_user.id)
    try:
        await callback.message.delete()
    except Exception:
        logger.info("Согласие отклонено: не удалось удалить сообщение.", exc_info=True)
    await callback.message.answer(
        CONSENT_REJECTED,
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
    )
    await callback.answer()


# ─── Сохранённый профиль (use_saved / new) ────────────────────────────


@router.callback_query(F.data == "use_saved_profile", AdmissionForm.saved_profile_choice)
@safe_handler
async def use_saved_profile_od(
    callback: types.CallbackQuery, state: FSMContext, user_repository: UserRepository
):
    saved = await user_repository.get_saved_profile(callback.from_user.id)
    if not saved:
        await state.set_state(AdmissionForm.fio)
        await safe_edit_text(callback.message, FORM_ASK_FIO, reply_markup=cancel_input_kb(), parse_mode="HTML")
        await callback.answer()
        return
    await state.update_data(fio=saved["fio"], phone=saved["phone"], email=saved["email"])
    await state.set_state(AdmissionForm.email)
    await safe_edit_text(
        callback.message,
        (
            f"Данные заполнены:\n<b>ФИО:</b> {saved['fio']}\n"
            f"<b>Телефон:</b> {saved['phone']}\n<b>Email:</b> {saved['email']}\n\n"
            "Отправьте email ещё раз для подтверждения или введите новый:"
        ),
        reply_markup=cancel_input_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "new_profile", AdmissionForm.saved_profile_choice)
@safe_handler
async def new_profile_od(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdmissionForm.fio)
    await safe_edit_text(callback.message, FORM_ASK_FIO, reply_markup=cancel_input_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "use_saved_profile", SpecialtyRequestForm.saved_profile_choice)
@safe_handler
async def use_saved_profile_spec(
    callback: types.CallbackQuery, state: FSMContext, user_repository: UserRepository
):
    saved = await user_repository.get_saved_profile(callback.from_user.id)
    if not saved:
        await state.set_state(SpecialtyRequestForm.fio)
        await safe_edit_text(
            callback.message, FORM_ASK_FIO_SPECIALTY, reply_markup=cancel_input_kb(), parse_mode="HTML"
        )
        await callback.answer()
        return
    await state.update_data(fio=saved["fio"], phone=saved["phone"], email=saved["email"])
    await state.set_state(SpecialtyRequestForm.confirm)
    await safe_edit_text(
        callback.message,
        (
            f"Давай перепроверим, всё ли правильно?\n"
            f"<b>ФИО:</b> {saved['fio']}\n<b>Почта:</b> {saved['email']}\n"
            f"<b>Телефон:</b> {saved['phone']}"
        ),
        reply_markup=specialty_confirm_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "new_profile", SpecialtyRequestForm.saved_profile_choice)
@safe_handler
async def new_profile_spec(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SpecialtyRequestForm.fio)
    await safe_edit_text(
        callback.message, FORM_ASK_FIO_SPECIALTY, reply_markup=cancel_input_kb(), parse_mode="HTML"
    )
    await callback.answer()
