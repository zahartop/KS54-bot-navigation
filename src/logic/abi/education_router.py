from __future__ import annotations

import logging

from aiogram import Router, types
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config.content import (
    BTN_BACK,
    BTN_BUDGET,
    BTN_MAIN_MENU,
    BTN_MIXED,
    BTN_PAID,
    EDUCATION_TEXTS,
    GRADE_TITLES,
)
from src.logic.abi.callbacks.education import (
    EducationFormCallback,
    EducationLevelCallback,
)
from src.utils.safe_handler import safe_handler
from src.utils.ui_utils import safe_edit_text

router = Router()
logger = logging.getLogger(__name__)


def _forms_keyboard(grade: str) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=BTN_BUDGET,
        callback_data=EducationFormCallback(grade=grade, form="budget").pack(),
    )
    builder.button(
        text=BTN_PAID,
        callback_data=EducationFormCallback(grade=grade, form="paid").pack(),
    )
    if grade == "11_class":
        builder.button(
            text=BTN_MIXED,
            callback_data=EducationFormCallback(grade=grade, form="mixed").pack(),
        )
    builder.button(text=BTN_BACK, callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def _form_details_keyboard(grade: str) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=BTN_BACK,
        callback_data=EducationLevelCallback(grade=grade).pack(),
    )
    builder.button(text=BTN_MAIN_MENU, callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(EducationLevelCallback.filter())
@safe_handler
async def education_level_screen(callback: types.CallbackQuery, callback_data: EducationLevelCallback) -> None:
    grade = callback_data.grade
    title = GRADE_TITLES.get(grade, "Уровень обучения")
    logger.info(
        "Переход в раздел обучения: user_id=%s, grade=%s",
        callback.from_user.id,
        grade,
    )
    await safe_edit_text(callback.message, title, reply_markup=_forms_keyboard(grade))
    await callback.answer()


@router.callback_query(EducationFormCallback.filter())
@safe_handler
async def education_form_screen(callback: types.CallbackQuery, callback_data: EducationFormCallback) -> None:
    key = (callback_data.grade, callback_data.form)
    logger.info(
        "Выбор формы обучения: user_id=%s, grade=%s, form=%s",
        callback.from_user.id,
        callback_data.grade,
        callback_data.form,
    )
    text = EDUCATION_TEXTS.get(
        key,
        "Информация по выбранной форме обучения пока не добавлена.",
    )
    await safe_edit_text(
        callback.message,
        text,
        reply_markup=_form_details_keyboard(callback_data.grade),
        parse_mode="HTML",
    )
    await callback.answer()
