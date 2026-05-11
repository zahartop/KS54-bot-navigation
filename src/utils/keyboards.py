from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config.content import (
    BTN_ABOUT_COLLEGE,
    BTN_BACK,
    BTN_CAREER,
    BTN_COLLEGE_HISTORY,
    BTN_CONTACT,
    BTN_FIND_SPECIALTY,
    BTN_HOW_TO_APPLY,
    BTN_OPEN_DAY,
    BTN_PRIVACY_POLICY,
    BTN_SPECIALTIES_9,
    BTN_SPECIALTIES_11,
    BTN_WEBSITE,
    COLLEGE_WEBSITE_URL,
    POLICY_URL,
)
from src.logic.abi.callbacks.education import EducationLevelCallback


class KeyboardFactory:
    """Фабрика для создания Inline-клавиатур на основе структуры меню."""

    @staticmethod
    def create_main_menu_keyboard() -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text=BTN_ABOUT_COLLEGE, callback_data="about_college")
        builder.button(text=BTN_COLLEGE_HISTORY, callback_data="college_history")
        builder.button(
            text=BTN_SPECIALTIES_9,
            callback_data=EducationLevelCallback(grade="9_class").pack(),
        )
        builder.button(
            text=BTN_SPECIALTIES_11,
            callback_data=EducationLevelCallback(grade="11_class").pack(),
        )
        builder.button(text=BTN_FIND_SPECIALTY, callback_data="find_specialty")
        builder.button(text=BTN_HOW_TO_APPLY, callback_data="how_to_apply")
        builder.button(text=BTN_CAREER, callback_data="career_opportunities")
        builder.button(text=BTN_OPEN_DAY, callback_data="open_day")
        builder.button(text=BTN_CONTACT, callback_data="contact_us")
        url = (POLICY_URL or "").strip()
        if url:
            builder.button(text=BTN_PRIVACY_POLICY, url=url)
        builder.button(text=BTN_WEBSITE, url=COLLEGE_WEBSITE_URL)
        builder.adjust(1)
        return builder.as_markup()

    @staticmethod
    def create_submenu_keyboard(current_menu_id: str) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text=BTN_BACK, callback_data="main_menu"))
        return builder.as_markup()
