"""Клавиатуры дерева опроса: регион → класс → специальность."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config.content import SURVEY_SPECIALTIES


def region_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Москва", callback_data="survey_region:moscow"))
    builder.row(InlineKeyboardButton(text="Московская область", callback_data="survey_region:mo"))
    builder.row(InlineKeyboardButton(text="Другой регион", callback_data="survey_region:other"))
    builder.row(InlineKeyboardButton(text="🏠 В главное меню", callback_data="main_menu"))
    return builder.as_markup()


def grade_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="После 9 класса", callback_data="survey_grade:9"))
    builder.row(InlineKeyboardButton(text="После 11 класса", callback_data="survey_grade:11"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="survey_back_region"))
    return builder.as_markup()


def specialty_kb(grade: str) -> InlineKeyboardMarkup:
    specs = SURVEY_SPECIALTIES.get(grade, {})
    builder = InlineKeyboardBuilder()
    for key, label in specs.items():
        builder.row(InlineKeyboardButton(text=label, callback_data=f"survey_spec:{key}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="survey_back_grade"))
    return builder.as_markup()
