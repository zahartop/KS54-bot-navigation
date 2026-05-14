"""Хендлеры Дня открытых дверей: выбор даты + форма ФИО→Телефон→Email→Регистрация."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.application.schemas.enrollment_events import EnrollmentEvent
from src.config.content import (
    BACK_TO_MENU_MESSAGE,
    CANCEL_MESSAGE,
    DOD_ASK_ROLE,
    DOD_ROLE_LABELS,
    FINAL_PD_CONSENT_TEXT,
    FORM_DB_TECHNICAL_ERROR,
    FORM_ERROR_EMAIL,
    FORM_ERROR_FIO,
    FORM_ERROR_PHONE,
    FORM_ERROR_SESSION,
    FORM_FIO_ACCEPTED,
    FORM_PHONE_ACCEPTED,
    OPEN_DAY_DUPLICATE,
    OPEN_DAY_SUCCESS,
    WELCOME_MESSAGE,
)
from src.data.user_repository import UserRepository
from src.infrastructure.kafka_enrollment import get_kafka_producer
from src.logic.abi.dod_reminders import schedule_open_day_reminders
from src.logic.abi.handlers.shared import (
    extract_text,
    is_valid_email,
    is_valid_fio,
    is_valid_phone,
    normalize_phone,
    notify_admin,
)
from src.logic.abi.keyboards.kb import (
    REPLY_KB_REMOVE,
    back_to_main_menu_kb,
    cancel_input_kb,
    dates_kb,
    dod_role_kb,
    final_consent_kb,
    phone_request_kb,
)
from src.logic.abi.states.admission_form import AdmissionForm
from src.services.integrations import IntegrationService
from src.services.webhooks import WebhookService
from src.utils.consent_flow import enter_open_day_form_after_policy
from src.utils.keyboards import KeyboardFactory
from src.utils.safe_handler import safe_handler
from src.utils.ui_utils import delete_prev_message, safe_edit_text, track_message

router = Router()
logger = logging.getLogger(__name__)


async def _try_delete(message: types.Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


@router.message(F.text == "День открытых дверей")
@safe_handler
async def open_day_dates_menu(message: types.Message):
    await message.answer("Выберите дату Дня открытых дверей:", reply_markup=dates_kb())


@router.callback_query(F.data == "open_day")
@safe_handler
async def open_day_dates_from_menu(callback: types.CallbackQuery):
    await callback.answer("Загружаю расписание...")
    await safe_edit_text(
        callback.message,
        "Выберите дату Дня открытых дверей:",
        reply_markup=dates_kb(),
    )


@router.callback_query(F.data.startswith("open_day_date:"))
@safe_handler
async def open_day_date_selected(
    callback: types.CallbackQuery, state: FSMContext, user_repository: UserRepository
):
    selected_date = callback.data.split("open_day_date:", maxsplit=1)[1]
    logger.info("Выбрана дата ДОД: user_id=%s, date=%s", callback.from_user.id, selected_date)
    await enter_open_day_form_after_policy(callback, state, selected_date, user_repository)
    await callback.answer()


@router.callback_query(F.data == "open_day_back")
@safe_handler
async def open_day_back_to_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_text(
        callback.message,
        BACK_TO_MENU_MESSAGE,
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── Форма ДОД: FIO → Phone → Email → Регистрация ────────────────────


@router.message(AdmissionForm.fio)
@safe_handler
async def process_fio(message: types.Message, state: FSMContext, bot: Bot):
    await delete_prev_message(bot, message.chat.id, state)
    fio = await extract_text(message)
    if fio is None:
        return
    if not is_valid_fio(fio):
        await message.answer(FORM_ERROR_FIO, reply_markup=cancel_input_kb())
        return
    await _try_delete(message)
    await state.update_data(fio=fio)
    await state.set_state(AdmissionForm.phone)
    sent = await message.answer(FORM_FIO_ACCEPTED, reply_markup=phone_request_kb(), parse_mode="HTML")
    await track_message(sent, state)


@router.message(AdmissionForm.phone, F.text == "Отмена ❌")
@safe_handler
async def process_phone_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(CANCEL_MESSAGE, reply_markup=REPLY_KB_REMOVE)
    await message.answer(
        WELCOME_MESSAGE,
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(AdmissionForm.phone, F.contact)
@safe_handler
async def process_phone(message: types.Message, state: FSMContext, bot: Bot):
    await delete_prev_message(bot, message.chat.id, state)
    raw_phone = message.contact.phone_number if message.contact else None
    if not raw_phone:
        await message.answer(FORM_ERROR_PHONE, reply_markup=phone_request_kb())
        return
    phone = normalize_phone(raw_phone)
    if not is_valid_phone(phone):
        await message.answer(FORM_ERROR_PHONE, reply_markup=phone_request_kb())
        return
    await _try_delete(message)
    await state.update_data(phone=phone)
    await state.set_state(AdmissionForm.email)
    sent = await message.answer(FORM_PHONE_ACCEPTED, reply_markup=REPLY_KB_REMOVE, parse_mode="HTML")
    await track_message(sent, state)


@router.message(AdmissionForm.phone, F.text)
@safe_handler
async def process_phone_wrong_input(message: types.Message):
    await message.answer(
        "Отправьте номер кнопкой «📱 Отправить номер телефона» или нажмите «Отмена ❌».",
        reply_markup=phone_request_kb(),
    )


@router.message(AdmissionForm.phone)
@safe_handler
async def process_phone_non_text(message: types.Message):
    await message.answer(
        "Отправьте номер кнопкой «📱 Отправить номер телефона».",
        reply_markup=phone_request_kb(),
    )


@router.message(AdmissionForm.email)
@safe_handler
async def process_email(message: types.Message, state: FSMContext, bot: Bot):
    await delete_prev_message(bot, message.chat.id, state)
    email = await extract_text(message)
    if email is None:
        return
    if not is_valid_email(email):
        await message.answer(FORM_ERROR_EMAIL, reply_markup=cancel_input_kb())
        return
    await _try_delete(message)
    await state.update_data(email=email)
    await state.set_state(AdmissionForm.role)
    await message.answer(DOD_ASK_ROLE, reply_markup=dod_role_kb())


@router.callback_query(F.data.startswith("dod_role:"), AdmissionForm.role)
@safe_handler
async def process_role(callback: types.CallbackQuery, state: FSMContext):
    role_key = callback.data.split("dod_role:", maxsplit=1)[1]
    role_label = DOD_ROLE_LABELS.get(role_key, role_key)
    await state.update_data(role=role_label)
    await state.set_state(AdmissionForm.pd_consent)
    await safe_edit_text(
        callback.message,
        FINAL_PD_CONSENT_TEXT,
        reply_markup=final_consent_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "final_consent_accept", AdmissionForm.pd_consent)
@safe_handler
async def dod_consent_accept(
    callback: types.CallbackQuery,
    state: FSMContext,
    user_repository: UserRepository,
    bot: Bot,
    scheduler: AsyncIOScheduler,
    webhook_service: WebhookService,
    integration_service: IntegrationService,
):
    data = await state.get_data()
    fio = data.get("fio")
    phone = data.get("phone")
    email = data.get("email")
    open_day_date = data.get("open_day_date")
    role_label = data.get("role")

    if not fio or not phone or not email or not open_day_date or not role_label:
        await state.clear()
        await callback.message.answer(FORM_ERROR_SESSION)
        await callback.answer()
        return

    user_id = callback.from_user.id

    is_dup = await user_repository.is_open_day_duplicate(user_id, open_day_date)
    if is_dup:
        await state.clear()
        await safe_edit_text(
            callback.message,
            OPEN_DAY_DUPLICATE.format(date=open_day_date),
            reply_markup=back_to_main_menu_kb(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await user_repository.mark_policy_accepted(user_id)

    app_id = await user_repository.register_abiturient(
        {
            "kind": "open_day",
            "telegram_user_id": user_id,
            "fio": fio,
            "phone": phone,
            "email": email,
            "open_day_date": open_day_date,
            "role": role_label,
        }
    )
    if app_id is None:
        await callback.message.answer(FORM_DB_TECHNICAL_ERROR)
        await callback.answer()
        return

    logger.info("Анкета ДОД сохранена: user_id=%s, date=%s, role=%s", user_id, open_day_date, role_label)
    payload = {
        "kind": "open_day",
        "app_id": app_id,
        "telegram_user_id": user_id,
        "fio": fio,
        "phone": phone,
        "email": email,
        "open_day_date": open_day_date,
        "role": role_label,
    }
    if webhook_service.enabled:
        asyncio.create_task(webhook_service.send_application(payload))
    asyncio.create_task(integration_service.send_to_docflow(payload))

    schedule_open_day_reminders(
        scheduler,
        application_id=app_id,
        telegram_user_id=user_id,
        open_day_date=open_day_date,
    )
    await notify_admin(
        bot, user_repository,
        app_id=app_id,
        form_type="📅 День открытых дверей",
        fio=fio,
        detail=f"Дата ДОД: {open_day_date} | Роль: {role_label}",
    )
    kp = get_kafka_producer()
    if kp is not None:
        await kp.publish_enrollment(
            EnrollmentEvent(
                user_id=user_id,
                event_type="open_day_registered",
                payload={
                    "app_id": app_id,
                    "fio": fio,
                    "phone": phone,
                    "email": email,
                    "open_day_date": open_day_date,
                    "role": role_label,
                },
            )
        )
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        OPEN_DAY_SUCCESS.format(
            app_id=app_id, fio=fio, phone=phone, email=email,
            date=open_day_date, role=role_label,
        ),
        reply_markup=back_to_main_menu_kb(),
        parse_mode="HTML",
    )
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "final_consent_reject", AdmissionForm.pd_consent)
@safe_handler
async def dod_consent_reject(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_text(
        callback.message,
        BACK_TO_MENU_MESSAGE,
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
