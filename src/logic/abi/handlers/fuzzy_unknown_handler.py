"""Подсказка по похожей команде, если пользователь ввёл /... с опечаткой."""

from __future__ import annotations

import difflib
import logging

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from src.utils.keyboards import KeyboardFactory
from src.utils.safe_handler import safe_handler

router = Router(name="fuzzy_commands")
logger = logging.getLogger(__name__)

_KNOWN_COMMANDS = ("/start", "/help", "/about", "/admin")


def _normalize_cmd(text: str) -> str:
    part = text.strip().split(maxsplit=1)[0]
    return part.split("@", maxsplit=1)[0].lower()


def _is_unknown_slash_command(text: str | None) -> bool:
    if not text:
        return False
    t = text.strip()
    if not t.startswith("/"):
        return False
    return _normalize_cmd(t) not in _KNOWN_COMMANDS


@router.message(F.text.func(_is_unknown_slash_command))
@safe_handler
async def suggest_closest_command(message: types.Message, state: FSMContext):
    """Если состояние FSM пустое и команда не из известных — предложить ближайшую."""
    if await state.get_state() is not None:
        return
    cmd = _normalize_cmd(message.text or "")
    matches = difflib.get_close_matches(cmd, _KNOWN_COMMANDS, n=1, cutoff=0.55)
    if not matches:
        await message.answer(
            "Неизвестная команда. Доступны: /start, /help, /about. Админам: /admin",
            reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        )
        return
    hint = matches[0]
    logger.info("fuzzy command: user_id=%s typed=%s suggest=%s", message.from_user.id, cmd, hint)
    await message.answer(
        f"Команда <code>{cmd}</code> не найдена. Возможно, вы имели в виду <b>{hint}</b>?",
        reply_markup=KeyboardFactory.create_main_menu_keyboard(),
        parse_mode="HTML",
    )
