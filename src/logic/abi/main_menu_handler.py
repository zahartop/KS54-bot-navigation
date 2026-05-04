from __future__ import annotations

import html
import logging
import re

from aiogram import Bot, F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from email_validator import EmailNotValidError, validate_email

from src.config.content import (
    ABOUT_MESSAGE,
    ADMIN_NEW_APPLICATION,
    BACK_TO_MENU_MESSAGE,
    CANCEL_MESSAGE,
    CONSENT_ERROR,
    CONSENT_REJECTED,
    FORM_ASK_FIO,
    FORM_ASK_FIO_SPECIALTY,
    FORM_DB_TECHNICAL_ERROR,
    FORM_ERROR_EMAIL,
    FORM_ERROR_FIO,
    FORM_ERROR_PHONE,
    FORM_ERROR_SESSION,
    FORM_FIO_ACCEPTED,
    FORM_PHONE_ACCEPTED,
    HELP_MESSAGE,
    NEXT_FORM_AFTER_CONSENT_BROWSE,
    OPEN_DAY_DUPLICATE,
    OPEN_DAY_SUCCESS,
    PLACEHOLDER_SECTIONS,
    SECTION_NOT_FOUND,
    SPECIALTY_DUPLICATE,
    SPECIALTY_SUCCESS,
    TEST_RESULTS,
    WELCOME_MESSAGE,
)
from src.data.user_repository import UserRepository
from src.logic.abi.dod_reminders import schedule_open_day_reminders
from src.logic.abi.keyboards.kb import (
    back_to_main_menu_kb,
    cancel_input_kb,
    dates_kb,
    specialty_confirm_kb,
)
from src.logic.abi.states.admission_form import (
    AdmissionForm,
    ConsentState,
    SpecialtyRequestForm,
    TestState,
)
from src.utils.consent_flow import enter_open_day_form_after_policy
from src.utils.keyboards import KeyboardFactory
from src.utils.pii import mask_pii
from src.utils.safe_handler import safe_handler
from src.utils.ui_utils import safe_edit_text

router = Router()
logger = logging.getLogger(__name__)

FIO_PATTERN = re.compile(r"^[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)*(?:\s+[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)*)+$")
PHONE_PATTERN = re.compile(r"^(?:\+7\d{10}|8\d{10})$")

_TYPO_TLDS: frozenset[str] = frozenset(
    {
        "con",
        "cmo",
        "ocm",
        "cpm",
        "cob",
        "om",
        "cm",
        "nt",
        "ne",
        "nrt",
        "og",
        "rg",
        "orgg",
        "ur",
        "ruu",
    }
)


async def _notify_admin(
    bot: Bot,
    user_repository: UserRepository,
    *,
    app_id: int,
    form_type: str,
    fio: str,
    detail: str,
) -> None:
    """Push администраторам: только замаскированное ФИО и ссылка в бота (без телефона и полного ФИО)."""

    admin_ids = await user_repository.get_admin_telegram_user_ids()
    if not admin_ids:
        return

    me = await bot.get_me()
    bot_username = (me.username or "").strip()
    if bot_username:
        admin_bot_url = f"https://t.me/{bot_username}"
        admin_panel_hint = (
            f'<a href="{html.escape(admin_bot_url, quote=True)}">Открыть бота</a> '
            "→ команда /admin → раздел «Новые заявки» (заявка "
            f"<b>№{html.escape(str(app_id), quote=True)}</b>)."
        )
    else:
        admin_panel_hint = (
            "Откройте этого бота в Telegram → /admin → «Новые заявки» "
            f"(заявка <b>№{html.escape(str(app_id), quote=True)}</b>)."
        )

    fio_masked = html.escape(mask_pii(fio), quote=True)
    detail_safe = html.escape(detail, quote=True)
    detail_line = f"📅 {detail_safe}" if detail.strip() else ""

    text = ADMIN_NEW_APPLICATION.format(
        app_id=app_id,
        form_type=html.escape(form_type, quote=True),
        fio_masked=fio_masked,
        detail_line=detail_line,
        admin_panel_hint=admin_panel_hint,
    )

    for admin_tid in admin_ids:
        try:
            await bot.send_message(admin_tid, text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            logger.warning(
                "Не удалось отправить уведомление администратору: admin_tid=%s",
                admin_tid,
                exc_info=True,
            )


# ─── Callback-данные ──────────────────────────────────────────────────────────


class TestAnswerCallback(CallbackData, prefix="test_answer"):
    question: int
    option: str


# ─── Тест на специальность ────────────────────────────────────────────────────

TEST_QUESTIONS = [
    {
        "state": TestState.q1,
        "text": "Вопрос 1\nЧто вам интереснее делать руками?",
        "answers": [
            "Писать алгоритм или код",
            "Обжимать кабель или настраивать Wi-Fi",
            "Паять или менять экран на телефоне",
        ],
    },
    {
        "state": TestState.q2,
        "text": "Вопрос 2\nКакой подарок для вас круче?",
        "answers": [
            "Курс Python",
            "Мощный роутер или управление коммутатором",
            "Набор отверток или паяльная станция",
        ],
    },
    {
        "state": TestState.q3,
        "text": "Вопрос 3\nЕсли в Колледже сломается техника, что вы пойдете чинить?",
        "answers": [
            "Сайт Колледжа или базу данных",
            "Интернет во всем корпусе",
            "Компьютеры в кабинете или проектор",
        ],
    },
    {
        "state": TestState.q4,
        "text": "Вопрос 4\nКакую новость вы прочитаете первой?",
        "answers": [
            "Вышел новый фреймворк для нейросетей",
            "Найдена дыра в защите мировых серверов",
            "Вышел новый процессор на уникальной архитектуре",
        ],
    },
    {
        "state": TestState.q5,
        "text": "Вопрос 5\nВаша идеальная подработка летом?",
        "answers": [
            "Делать чат-ботов на заказ",
            "Тянуть локальную сеть в офисах",
            "Мастер по ремонту электроники",
        ],
    },
]


# ─── Валидация ───────────────────────────────────────────────────────────────


def _is_valid_phone(phone: str) -> bool:
    return bool(PHONE_PATTERN.fullmatch(phone))


def _is_valid_email(email: str) -> bool:
    if not email:
        return False
    try:
        result = validate_email(email, check_deliverability=False)
        tld = result.ascii_domain.rsplit(".", 1)[-1].lower()
        return tld not in _TYPO_TLDS
    except EmailNotValidError:
        return False


def _is_valid_fio(fio: str) -> bool:
    return bool(FIO_PATTERN.fullmatch(fio))


def _build_test_question_keyboard(question_index: int, answers: list[str]) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    options = ["A", "B", "C"]
    for idx, answer_text in enumerate(answers):
        builder.button(
            text=answer_text,
            callback_data=TestAnswerCallback(question=question_index, option=options[idx]).pack(),
        )
    builder.button(text="🏠 В главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


async def _send_test_question(
    target: types.Message | types.CallbackQuery,
    question_index: int,
    state: FSMContext,
) -> None:
    question = TEST_QUESTIONS[question_index - 1]
    await state.set_state(question["state"])
    reply_markup = _build_test_question_keyboard(question_index, question["answers"])
    if isinstance(target, types.CallbackQuery):
        await safe_edit_text(target.message, question["text"], reply_markup=reply_markup)
    else:
        await target.answer(question["text"], reply_markup=reply_markup)


def _detect_test_result(score_a: int, score_b: int, score_c: int) -> str:
    score_map = {"A": score_a, "B": score_b, "C": score_c}
    return max(score_map, key=lambda key: score_map[key])


async def _extract_text(message: types.Message) -> str | None:
    if not message.text:
        await message.answer("Пожалуйста, введите текст", reply_markup=cancel_input_kb())
        return None
    return message.text.strip()


# ─── Главное меню ────────────────────────────────────────────────────────────


@router.message(CommandStart())
@safe_handler
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    logger.info("Пользователь открыл главное меню: user_id=%s", message.from_user.id)
    await message.answer(
        WELCOME_MESSAGE,
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("help"))
@safe_handler
async def cmd_help(message: types.Message):
    await message.answer(HELP_MESSAGE, parse_mode="HTML")


@router.message(Command("about"))
@safe_handler
async def cmd_about(message: types.Message):
    await message.answer(ABOUT_MESSAGE, parse_mode="HTML")


@router.callback_query(F.data == "main_menu")
@safe_handler
async def back_to_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_text(
        callback.message,
        BACK_TO_MENU_MESSAGE,
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_input")
@safe_handler
async def cancel_input(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_text(
        callback.message,
        CANCEL_MESSAGE,
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── День открытых дверей ────────────────────────────────────────────────────


@router.message(F.text == "День открытых дверей")
@safe_handler
async def open_day_dates_menu(message: types.Message):
    await message.answer("Выберите дату Дня открытых дверей:", reply_markup=dates_kb())


@router.callback_query(F.data == "open_day")
@safe_handler
async def open_day_dates_from_menu(callback: types.CallbackQuery):
    await safe_edit_text(
        callback.message,
        "Выберите дату Дня открытых дверей:",
        reply_markup=dates_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("open_day_date:"))
@safe_handler
async def open_day_date_selected(callback: types.CallbackQuery, state: FSMContext):
    selected_date = callback.data.split("open_day_date:", maxsplit=1)[1]
    logger.info("Выбрана дата ДОД: user_id=%s, date=%s", callback.from_user.id, selected_date)
    await enter_open_day_form_after_policy(callback, state, selected_date)
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


# ─── Подбор специальности ────────────────────────────────────────────────────


@router.callback_query(F.data == "find_specialty")
@safe_handler
async def start_specialty_request(callback: types.CallbackQuery, state: FSMContext):
    logger.info("Старт анкеты подбора специальности: user_id=%s", callback.from_user.id)
    await state.clear()
    await state.update_data(next_form="specialty")
    await state.set_state(SpecialtyRequestForm.fio)
    await callback.message.answer(FORM_ASK_FIO_SPECIALTY, reply_markup=cancel_input_kb(), parse_mode="HTML")
    await callback.answer()


# ─── Экран согласия ──────────────────────────────────────────────────────────


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
        await enter_open_day_form_after_policy(callback, state, str(open_day_date))
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
            logger.info("Согласие (специальность): не удалось удалить сообщение с экраном политики.", exc_info=True)
        await state.set_state(SpecialtyRequestForm.fio)
        await callback.message.answer(FORM_ASK_FIO_SPECIALTY, reply_markup=cancel_input_kb(), parse_mode="HTML")
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
        logger.info("Согласие отклонено: не удалось удалить сообщение с экраном политики.", exc_info=True)
    await callback.message.answer(
        CONSENT_REJECTED,
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
    )
    await callback.answer()


# ─── Форма ДОД ───────────────────────────────────────────────────────────────


@router.message(AdmissionForm.fio)
@safe_handler
async def process_fio(message: types.Message, state: FSMContext):
    fio = await _extract_text(message)
    if fio is None:
        return
    if not _is_valid_fio(fio):
        await message.answer(FORM_ERROR_FIO, reply_markup=cancel_input_kb())
        return
    await state.update_data(fio=fio)
    await state.set_state(AdmissionForm.phone)
    await message.answer(FORM_FIO_ACCEPTED, reply_markup=cancel_input_kb(), parse_mode="HTML")


@router.message(AdmissionForm.phone)
@safe_handler
async def process_phone(message: types.Message, state: FSMContext):
    phone = await _extract_text(message)
    if phone is None:
        return
    if not _is_valid_phone(phone):
        await message.answer(FORM_ERROR_PHONE, reply_markup=cancel_input_kb())
        return
    await state.update_data(phone=phone)
    await state.set_state(AdmissionForm.email)
    await message.answer(FORM_PHONE_ACCEPTED, reply_markup=cancel_input_kb(), parse_mode="HTML")


@router.message(AdmissionForm.email)
@safe_handler
async def process_email(
    message: types.Message,
    state: FSMContext,
    user_repository: UserRepository,
    bot: Bot,
    scheduler: AsyncIOScheduler,
):
    email = await _extract_text(message)
    if email is None:
        return
    if not _is_valid_email(email):
        await message.answer(FORM_ERROR_EMAIL, reply_markup=cancel_input_kb())
        return

    data = await state.get_data()
    fio = data.get("fio")
    phone = data.get("phone")
    open_day_date = data.get("open_day_date")

    if not fio or not phone or not open_day_date:
        await state.clear()
        await message.answer(FORM_ERROR_SESSION)
        return

    user_id = message.from_user.id

    # Защита от дублей
    is_dup = await user_repository.is_open_day_duplicate(user_id, open_day_date)
    if is_dup:
        await state.clear()
        await message.answer(
            OPEN_DAY_DUPLICATE.format(date=open_day_date),
            reply_markup=back_to_main_menu_kb(),
            parse_mode="HTML",
        )
        return

    app_id = await user_repository.register_abiturient(
        {
            "kind": "open_day",
            "telegram_user_id": user_id,
            "fio": fio,
            "phone": phone,
            "email": email,
            "open_day_date": open_day_date,
        }
    )
    if app_id is None:
        await message.answer(FORM_DB_TECHNICAL_ERROR)
        return

    logger.info("Анкета ДОД сохранена: user_id=%s, date=%s", user_id, open_day_date)
    schedule_open_day_reminders(
        scheduler,
        application_id=app_id,
        telegram_user_id=user_id,
        open_day_date=open_day_date,
    )
    await _notify_admin(
        bot,
        user_repository,
        app_id=app_id,
        form_type="📅 День открытых дверей",
        fio=fio,
        detail=f"Дата ДОД: {open_day_date}",
    )
    await message.answer(
        OPEN_DAY_SUCCESS.format(app_id=app_id, fio=fio, phone=phone, email=email, date=open_day_date),
        reply_markup=back_to_main_menu_kb(),
        parse_mode="HTML",
    )
    await state.clear()


# ─── Форма подбора специальности ─────────────────────────────────────────────


@router.message(SpecialtyRequestForm.fio)
@safe_handler
async def process_specialty_fio(message: types.Message, state: FSMContext):
    fio = await _extract_text(message)
    if fio is None:
        return
    if not _is_valid_fio(fio):
        await message.answer(FORM_ERROR_FIO, reply_markup=cancel_input_kb())
        return
    await state.update_data(fio=fio)
    await state.set_state(SpecialtyRequestForm.phone)
    await message.answer(FORM_FIO_ACCEPTED, reply_markup=cancel_input_kb(), parse_mode="HTML")


@router.message(SpecialtyRequestForm.phone)
@safe_handler
async def process_specialty_phone(message: types.Message, state: FSMContext):
    phone = await _extract_text(message)
    if phone is None:
        return
    if not _is_valid_phone(phone):
        await message.answer(FORM_ERROR_PHONE, reply_markup=cancel_input_kb())
        return
    await state.update_data(phone=phone)
    await state.set_state(SpecialtyRequestForm.email)
    await message.answer(FORM_PHONE_ACCEPTED, reply_markup=cancel_input_kb(), parse_mode="HTML")


@router.message(SpecialtyRequestForm.email)
@safe_handler
async def process_specialty_email(message: types.Message, state: FSMContext):
    email = await _extract_text(message)
    if email is None:
        return
    if not _is_valid_email(email):
        await message.answer(FORM_ERROR_EMAIL, reply_markup=cancel_input_kb())
        return

    await state.update_data(email=email)
    data = await state.get_data()
    fio = data.get("fio", "")
    phone = data.get("phone", "")

    await state.set_state(SpecialtyRequestForm.confirm)
    await message.answer(
        f"Давай перепроверим, всё ли правильно?\n<b>ФИО:</b> {fio}\n<b>Почта:</b> {email}\n<b>Телефон:</b> {phone}",
        reply_markup=specialty_confirm_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "specialty_confirm", SpecialtyRequestForm.confirm)
@safe_handler
async def specialty_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    fio = data.get("fio")
    phone = data.get("phone")
    email = data.get("email")

    if not fio or not phone or not email:
        await state.clear()
        await safe_edit_text(callback.message, FORM_ERROR_SESSION)
        await callback.answer()
        return

    await state.update_data(score_a=0, score_b=0, score_c=0)
    logger.info("Анкета подбора подтверждена, старт теста: user_id=%s", callback.from_user.id)
    await safe_edit_text(callback.message, "Отлично, начинаем тест!")
    await _send_test_question(callback, question_index=1, state=state)
    await callback.answer()


@router.callback_query(TestAnswerCallback.filter())
@safe_handler
async def handle_test_answer(
    callback: types.CallbackQuery,
    callback_data: TestAnswerCallback,
    state: FSMContext,
    user_repository: UserRepository,
    bot: Bot,
):
    data = await state.get_data()
    score_a = int(data.get("score_a", 0))
    score_b = int(data.get("score_b", 0))
    score_c = int(data.get("score_c", 0))

    if callback_data.option == "A":
        score_a += 1
    elif callback_data.option == "B":
        score_b += 1
    else:
        score_c += 1

    await state.update_data(score_a=score_a, score_b=score_b, score_c=score_c)

    current_question = callback_data.question
    if current_question < 5:
        await _send_test_question(callback, question_index=current_question + 1, state=state)
        await callback.answer()
        return

    await state.set_state(TestState.show_result)
    result_key = _detect_test_result(score_a, score_b, score_c)
    result_text = TEST_RESULTS[result_key]

    fio = data.get("fio")
    phone = data.get("phone")
    email = data.get("email")
    if not fio or not phone or not email:
        await state.clear()
        await safe_edit_text(callback.message, FORM_ERROR_SESSION)
        await callback.answer()
        return

    user_id = callback.from_user.id

    # Защита от дублей
    is_dup = await user_repository.is_specialty_duplicate(user_id)
    if is_dup:
        await state.clear()
        await safe_edit_text(
            callback.message,
            SPECIALTY_DUPLICATE,
            reply_markup=back_to_main_menu_kb(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    app_id = await user_repository.register_abiturient(
        {
            "kind": "specialty",
            "telegram_user_id": user_id,
            "fio": fio,
            "phone": phone,
            "email": email,
            "test_result": result_key,
        }
    )
    if app_id is None:
        await safe_edit_text(callback.message, FORM_DB_TECHNICAL_ERROR)
        await callback.answer()
        return

    logger.info("Тест завершен: user_id=%s, result=%s", user_id, result_key)
    await _notify_admin(
        bot,
        user_repository,
        app_id=app_id,
        form_type="🎯 Подбор специальности",
        fio=fio,
        detail=f"Результат теста: {result_key}",
    )
    await safe_edit_text(
        callback.message,
        SPECIALTY_SUCCESS.format(app_id=app_id, fio=fio, phone=phone, email=email, result_text=result_text),
        reply_markup=back_to_main_menu_kb(),
        parse_mode="HTML",
    )
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "specialty_restart", SpecialtyRequestForm.confirm)
@safe_handler
async def specialty_restart(callback: types.CallbackQuery, state: FSMContext):
    """Повторный ввод анкеты (согласие уже в БД — сразу с ФИО)."""
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        logger.info("specialty_restart: не удалось удалить предыдущее сообщение.", exc_info=True)
    await state.update_data(next_form="specialty")
    await state.set_state(SpecialtyRequestForm.fio)
    await callback.message.answer(FORM_ASK_FIO_SPECIALTY, reply_markup=cancel_input_kb(), parse_mode="HTML")
    await callback.answer()


# ─── Навигация разделов меню (catch-all) ─────────────────────────────────────


@router.callback_query()
@safe_handler
async def handle_menu_navigation(callback: types.CallbackQuery, state: FSMContext):
    menu_id = callback.data
    section_text = PLACEHOLDER_SECTIONS.get(menu_id)

    if section_text:
        await safe_edit_text(
            callback.message,
            section_text,
            reply_markup=KeyboardFactory.create_submenu_keyboard("placeholder"),
            parse_mode="HTML",
        )
    else:
        await callback.answer(SECTION_NOT_FOUND, show_alert=True)
        return

    await callback.answer()


