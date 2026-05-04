from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config.content import (
    BTN_BACK,
    BTN_CANCEL_INPUT,
    BTN_CONSENT_ACCEPT,
    BTN_CONSENT_REJECT,
    BTN_MAIN_MENU,
    BTN_PRIVACY_POLICY,
    BTN_SPECIALTY_CONFIRM,
    BTN_SPECIALTY_RESTART,
    OPEN_DAY_DATES,
    POLICY_URL,
)


def dates_kb() -> InlineKeyboardMarkup:
    """Создает Inline-клавиатуру выбора даты Дня открытых дверей."""
    builder = InlineKeyboardBuilder()
    for date in OPEN_DAY_DATES:
        builder.button(text=date, callback_data=f"open_day_date:{date}")
    builder.button(text=BTN_BACK, callback_data="open_day_back")
    builder.adjust(1)
    return builder.as_markup()


def create_open_day_dates_keyboard() -> InlineKeyboardMarkup:
    """Совместимость со старым названием функции."""
    return dates_kb()


def back_to_main_menu_kb() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню."""
    builder = InlineKeyboardBuilder()
    builder.button(text=BTN_MAIN_MENU, callback_data="main_menu")
    return builder.as_markup()


def specialty_confirm_kb() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения анкеты подбора специальности."""
    builder = InlineKeyboardBuilder()
    builder.button(text=BTN_SPECIALTY_CONFIRM, callback_data="specialty_confirm")
    builder.button(text=BTN_SPECIALTY_RESTART, callback_data="specialty_restart")
    builder.adjust(1)
    return builder.as_markup()


def cancel_input_kb() -> InlineKeyboardMarkup:
    """Inline-кнопка выхода из режима ввода данных."""
    builder = InlineKeyboardBuilder()
    builder.button(text=BTN_CANCEL_INPUT, callback_data="cancel_input")
    builder.adjust(1)
    return builder.as_markup()


def get_consent_kb() -> InlineKeyboardMarkup:
    """Клавиатура экрана согласия на обработку ПДн (ФЗ-152)."""
    builder = InlineKeyboardBuilder()
    url = (POLICY_URL or "").strip()
    if url:
        builder.button(text=BTN_PRIVACY_POLICY, url=url)
    builder.button(text=BTN_CONSENT_ACCEPT, callback_data="consent_accept")
    builder.button(text=BTN_CONSENT_REJECT, callback_data="consent_reject")
    builder.adjust(1)
    return builder.as_markup()
