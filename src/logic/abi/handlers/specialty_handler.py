"""Хендлеры подбора специальности: форма + тест + результат."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router, types
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config.content import (
    FORM_DB_TECHNICAL_ERROR,
    FORM_ERROR_EMAIL,
    FORM_ERROR_FIO,
    FORM_ERROR_PHONE,
    FORM_ERROR_SESSION,
    FORM_FIO_ACCEPTED,
    FORM_PHONE_ACCEPTED,
    SPECIALTY_DUPLICATE,
    SPECIALTY_SUCCESS,
    SURVEY_ASK_REGION,
    TEST_RESULTS,
)
from src.data.user_repository import UserRepository
from src.logic.abi.handlers.shared import (
    extract_text,
    is_valid_email,
    is_valid_fio,
    is_valid_phone,
    notify_admin,
)
from src.logic.abi.keyboards.kb import back_to_main_menu_kb, cancel_input_kb, specialty_confirm_kb
from src.logic.abi.keyboards.survey_kb import region_kb
from src.logic.abi.states.admission_form import SpecialtyRequestForm, SurveyState, TestState
from src.services.integrations import IntegrationService
from src.services.webhooks import WebhookService
from src.utils.safe_handler import safe_handler
from src.utils.ui_utils import delete_prev_message, safe_edit_text, track_message

router = Router()
logger = logging.getLogger(__name__)


class TestAnswerCallback(CallbackData, prefix="test_answer"):
    question: int
    option: str


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


# ─── Форма: FIO → Phone → Email → Confirm → Тест ─────────────────────


@router.message(SpecialtyRequestForm.fio)
@safe_handler
async def process_specialty_fio(message: types.Message, state: FSMContext, bot: Bot):
    await delete_prev_message(bot, message.chat.id, state)
    fio = await extract_text(message)
    if fio is None:
        return
    if not is_valid_fio(fio):
        await message.answer(FORM_ERROR_FIO, reply_markup=cancel_input_kb())
        return
    await state.update_data(fio=fio)
    await state.set_state(SpecialtyRequestForm.phone)
    sent = await message.answer(FORM_FIO_ACCEPTED, reply_markup=cancel_input_kb(), parse_mode="HTML")
    await track_message(sent, state)


@router.message(SpecialtyRequestForm.phone)
@safe_handler
async def process_specialty_phone(message: types.Message, state: FSMContext, bot: Bot):
    await delete_prev_message(bot, message.chat.id, state)
    phone = await extract_text(message)
    if phone is None:
        return
    if not is_valid_phone(phone):
        await message.answer(FORM_ERROR_PHONE, reply_markup=cancel_input_kb())
        return
    await state.update_data(phone=phone)
    await state.set_state(SpecialtyRequestForm.email)
    sent = await message.answer(FORM_PHONE_ACCEPTED, reply_markup=cancel_input_kb(), parse_mode="HTML")
    await track_message(sent, state)


@router.message(SpecialtyRequestForm.email)
@safe_handler
async def process_specialty_email(message: types.Message, state: FSMContext, bot: Bot):
    await delete_prev_message(bot, message.chat.id, state)
    email = await extract_text(message)
    if email is None:
        return
    if not is_valid_email(email):
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
    webhook_service: WebhookService,
    integration_service: IntegrationService,
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

    is_dup = await user_repository.is_specialty_duplicate(user_id, fio=fio)
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
    payload = {
        "kind": "specialty",
        "app_id": app_id,
        "telegram_user_id": user_id,
        "fio": fio,
        "phone": phone,
        "email": email,
        "test_result": result_key,
    }
    if webhook_service.enabled:
        asyncio.create_task(webhook_service.send_application(payload))
    asyncio.create_task(integration_service.send_to_docflow(payload))

    await notify_admin(
        bot, user_repository,
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
    """Повторный ввод анкеты (согласие уже в БД — заново через опрос)."""
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        logger.info("specialty_restart: не удалось удалить сообщение.", exc_info=True)
    await state.update_data(next_form="specialty")
    await state.set_state(SurveyState.region)
    await callback.message.answer(SURVEY_ASK_REGION, reply_markup=region_kb())
    await callback.answer()
