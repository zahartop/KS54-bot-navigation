"""Деревовидный опрос перед анкетой подбора специальности.

Flow: Регион → Класс → Специальность → переход в SpecialtyRequestForm.fio
"""

from __future__ import annotations

import logging

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from src.config.content import (
    FORM_ASK_FIO_SPECIALTY,
    SAVED_PROFILE_PROMPT,
    SURVEY_ASK_GRADE,
    SURVEY_ASK_REGION,
    SURVEY_ASK_SPECIALTY,
    SURVEY_OTHER_REGION,
    SURVEY_SPECIALTIES,
)
from src.data.user_repository import UserRepository
from src.logic.abi.keyboards.kb import cancel_input_kb, saved_profile_kb
from src.logic.abi.keyboards.survey_kb import grade_kb, region_kb, specialty_kb
from src.logic.abi.states.admission_form import SpecialtyRequestForm, SurveyState
from src.utils.safe_handler import safe_handler
from src.utils.ui_utils import safe_edit_text

router = Router(name="survey")
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "find_specialty")
@safe_handler
async def start_survey(callback: types.CallbackQuery, state: FSMContext):
    logger.info("Старт опроса подбора специальности: user_id=%s", callback.from_user.id)
    await state.clear()
    await state.update_data(next_form="specialty")
    await state.set_state(SurveyState.region)
    await safe_edit_text(
        callback.message,
        SURVEY_ASK_REGION,
        reply_markup=region_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("survey_region:"), SurveyState.region)
@safe_handler
async def survey_region_selected(callback: types.CallbackQuery, state: FSMContext):
    region = callback.data.split("survey_region:", maxsplit=1)[1]
    logger.info("Опрос: регион=%s, user_id=%s", region, callback.from_user.id)

    if region == "other":
        await state.clear()
        await safe_edit_text(
            callback.message,
            SURVEY_OTHER_REGION,
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await state.update_data(survey_region=region)
    await state.set_state(SurveyState.grade)
    await safe_edit_text(
        callback.message,
        SURVEY_ASK_GRADE,
        reply_markup=grade_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "survey_back_region", SurveyState.grade)
@safe_handler
async def survey_back_to_region(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SurveyState.region)
    await safe_edit_text(
        callback.message,
        SURVEY_ASK_REGION,
        reply_markup=region_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("survey_grade:"), SurveyState.grade)
@safe_handler
async def survey_grade_selected(callback: types.CallbackQuery, state: FSMContext):
    grade = callback.data.split("survey_grade:", maxsplit=1)[1]
    logger.info("Опрос: класс=%s, user_id=%s", grade, callback.from_user.id)

    if grade not in SURVEY_SPECIALTIES:
        await callback.answer("Неизвестный класс", show_alert=True)
        return

    await state.update_data(survey_grade=grade)
    await state.set_state(SurveyState.specialty)
    await safe_edit_text(
        callback.message,
        SURVEY_ASK_SPECIALTY,
        reply_markup=specialty_kb(grade),
    )
    await callback.answer()


@router.callback_query(F.data == "survey_back_grade", SurveyState.specialty)
@safe_handler
async def survey_back_to_grade(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SurveyState.grade)
    await safe_edit_text(
        callback.message,
        SURVEY_ASK_GRADE,
        reply_markup=grade_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("survey_spec:"), SurveyState.specialty)
@safe_handler
async def survey_specialty_selected(
    callback: types.CallbackQuery, state: FSMContext, user_repository: UserRepository
):
    spec_key = callback.data.split("survey_spec:", maxsplit=1)[1]
    data = await state.get_data()
    grade = data.get("survey_grade", "")
    specs = SURVEY_SPECIALTIES.get(grade, {})
    spec_label = specs.get(spec_key, spec_key)

    logger.info(
        "Опрос завершён: user_id=%s, region=%s, grade=%s, spec=%s",
        callback.from_user.id,
        data.get("survey_region"),
        grade,
        spec_key,
    )

    await state.update_data(
        survey_specialty_key=spec_key,
        survey_specialty_label=spec_label,
    )
    try:
        await callback.message.delete()
    except Exception:
        logger.debug("survey: не удалось удалить сообщение с выбором специальности")

    saved = await user_repository.get_saved_profile(callback.from_user.id)
    if saved:
        await state.set_state(SpecialtyRequestForm.saved_profile_choice)
        await callback.message.answer(
            SAVED_PROFILE_PROMPT.format(fio=saved["fio"], phone=saved["phone"], email=saved["email"]),
            reply_markup=saved_profile_kb(saved["fio"]),
            parse_mode="HTML",
        )
    else:
        await state.set_state(SpecialtyRequestForm.fio)
        await callback.message.answer(
            FORM_ASK_FIO_SPECIALTY,
            reply_markup=cancel_input_kb(),
            parse_mode="HTML",
        )
    await callback.answer()
