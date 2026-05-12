from __future__ import annotations

from aiogram.types import (
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config.content import (
    BTN_BACK,
    BTN_CANCEL_INPUT,
    BTN_CONSENT_ACCEPT,
    BTN_CONSENT_REJECT,
    BTN_FINAL_CONSENT_ACCEPT,
    BTN_FINAL_CONSENT_REJECT,
    BTN_MAIN_MENU,
    BTN_PRIVACY_POLICY,
    BTN_SPECIALTY_CONFIRM,
    BTN_SPECIALTY_RESTART,
    OPEN_DAY_DATES,
    POLICY_URL,
)

REPLY_KB_REMOVE = ReplyKeyboardRemove()


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


def saved_profile_kb(saved_fio: str) -> InlineKeyboardMarkup:
    """Выбор: использовать сохранённые данные или ввести новые."""
    builder = InlineKeyboardBuilder()
    label = f"📋 Использовать: {saved_fio}" if len(saved_fio) <= 40 else "📋 Использовать сохранённые"
    builder.button(text=label, callback_data="use_saved_profile")
    builder.button(text="✏️ Ввести новые данные", callback_data="new_profile")
    builder.button(text=BTN_CANCEL_INPUT, callback_data="cancel_input")
    builder.adjust(1)
    return builder.as_markup()


def cancel_input_kb() -> InlineKeyboardMarkup:
    """Inline-кнопка выхода из режима ввода данных."""
    builder = InlineKeyboardBuilder()
    builder.button(text=BTN_CANCEL_INPUT, callback_data="cancel_input")
    builder.adjust(1)
    return builder.as_markup()


def phone_request_kb() -> ReplyKeyboardMarkup:
    """ReplyKeyboard с кнопкой отправки контакта для получения номера телефона."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)],
            [KeyboardButton(text="Отмена ❌")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def dod_role_kb() -> InlineKeyboardMarkup:
    """Выбор роли при записи на День открытых дверей."""
    from src.config.content import DOD_ROLE_LABELS

    builder = InlineKeyboardBuilder()
    for key, label in DOD_ROLE_LABELS.items():
        builder.button(text=label, callback_data=f"dod_role:{key}")
    builder.button(text=BTN_CANCEL_INPUT, callback_data="cancel_input")
    builder.adjust(1)
    return builder.as_markup()


def appeal_cancel_kb() -> InlineKeyboardMarkup:
    """Кнопка отмены при вводе обращения."""
    builder = InlineKeyboardBuilder()
    builder.button(text=BTN_CANCEL_INPUT, callback_data="cancel_input")
    builder.adjust(1)
    return builder.as_markup()


def final_consent_kb() -> InlineKeyboardMarkup:
    """Клавиатура финального согласия на обработку ПДн перед сохранением анкеты."""
    builder = InlineKeyboardBuilder()
    builder.button(text=BTN_FINAL_CONSENT_ACCEPT, callback_data="final_consent_accept")
    builder.button(text=BTN_FINAL_CONSENT_REJECT, callback_data="final_consent_reject")
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
