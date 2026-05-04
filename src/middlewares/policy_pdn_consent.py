"""Глобальная проверка ``is_policy_accepted`` перед обработкой сообщений и inline-кнопок."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, types
from aiogram.fsm.context import FSMContext
from aiogram.enums import MessageEntityType
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.config.content import CONSENT_PENDING_ALERT, NEXT_FORM_AFTER_CONSENT_BROWSE, OPEN_DAY_DATE_CHOSEN
from src.data.user_repository import UserRepository
from src.logic.abi.states.admission_form import ConsentState
from src.utils.admin_guard import user_is_bot_admin
from src.utils.consent_flow import send_consent_screen_for_message, show_consent_screen
from src.utils.ui_utils import safe_edit_text

logger = logging.getLogger(__name__)

_CONSENT_CALLBACKS = frozenset({"consent_accept", "consent_reject"})
_PUBLIC_COMMANDS = frozenset({"/start", "/help", "/about"})


def _event_user(event: TelegramObject) -> types.User | None:
    if isinstance(event, Message):
        return event.from_user
    if isinstance(event, CallbackQuery):
        return event.from_user
    return None


def _is_public_command_message(message: Message) -> bool:
    """Без принятой политики разрешаем только публичные slash-команды."""

    text = message.text
    if text:
        parts = text.strip().split()
        if parts:
            cmd = parts[0].split("@", maxsplit=1)[0].lower()
            if cmd in _PUBLIC_COMMANDS:
                return True
    if message.entities and text:
        for ent in message.entities:
            if ent.type != MessageEntityType.BOT_COMMAND:
                continue
            frag = text[ent.offset : ent.offset + ent.length].split("@", maxsplit=1)[0].lower()
            if frag in _PUBLIC_COMMANDS:
                return True
    return False


class PolicyPdnConsentMiddleware(BaseMiddleware):
    """PostgreSQL ``is_policy_accepted``: при False — отправка политики и блокировка хендлеров."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user = _event_user(event)
        state: FSMContext | None = data.get("state")
        repo: UserRepository | None = data.get("user_repository")

        if user is None or state is None or repo is None:
            return await handler(event, data)

        uid = int(user.id)

        try:
            if await user_is_bot_admin(uid, repo):
                return await handler(event, data)
            if await repo.check_policy_status(uid):
                return await handler(event, data)
        except Exception:
            logger.exception("PolicyPdnConsentMiddleware: проверка статуса user_id=%s", uid)
            await _fail_open(event)
            return None

        # Далее пользователь без согласия в БД: пропускаем только экран принятия/отказа —
        # хендер вызывает mark_policy_accepted / сброс.
        if isinstance(event, CallbackQuery) and ((event.data or "").strip() in _CONSENT_CALLBACKS):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            return await self._handle_callback_blocked(handler, event, state)

        assert isinstance(event, Message)
        if _is_public_command_message(event):
            return await handler(event, data)
        return await self._handle_message_blocked(event, state)

    async def _handle_callback_blocked(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        state: FSMContext,
    ) -> Any:
        cb_data = (event.data or "").strip()

        if cb_data.startswith("open_day_date:"):
            sel = cb_data.split("open_day_date:", maxsplit=1)[1]
            await state.update_data(open_day_date=sel, next_form="open_day")
            await state.set_state(ConsentState.waiting)
            if event.message:
                await safe_edit_text(event.message, OPEN_DAY_DATE_CHOSEN.format(date=sel), parse_mode="HTML")
            await show_consent_screen(event)
            await event.answer()
            return None

        if cb_data == "find_specialty":
            await state.clear()
            await state.update_data(next_form="specialty")
            await state.set_state(ConsentState.waiting)
            await show_consent_screen(event)
            await event.answer()
            return None

        if await state.get_state() == ConsentState.waiting.state:
            await event.answer(CONSENT_PENDING_ALERT, show_alert=True)
            return None

        return await handler(event, data)

    async def _handle_message_blocked(self, event: Message, state: FSMContext) -> Any:
        if await state.get_state() == ConsentState.waiting.state:
            await send_consent_screen_for_message(event, reminder_only_text=CONSENT_PENDING_ALERT)
            return None

        await state.clear()
        await state.update_data(next_form=NEXT_FORM_AFTER_CONSENT_BROWSE)
        await state.set_state(ConsentState.waiting)
        await send_consent_screen_for_message(event)
        return None


async def _fail_open(event: TelegramObject) -> None:
    try:
        if isinstance(event, CallbackQuery):
            await event.answer("Не удалось проверить статус согласия ПДн. Попробуйте позже.", show_alert=True)
        elif isinstance(event, Message):
            await event.answer("Не удалось проверить статус согласия ПДн. Попробуйте позже.")
    except Exception:
        logger.debug("PolicyPdnConsentMiddleware: ответ пользователю не отправлен")
