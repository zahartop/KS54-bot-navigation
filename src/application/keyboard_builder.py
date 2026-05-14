"""Универсальная сборка InlineKeyboard из JSON (JSONB в ``bot_content.buttons``)."""

from __future__ import annotations

import logging
from typing import Any

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

logger = logging.getLogger(__name__)


def build_inline_keyboard_from_json(buttons_json: Any) -> InlineKeyboardMarkup | None:
    """
    Ожидаемая структура: список рядов, каждый ряд — список кнопок::

        [
          [{"text": "A", "callback_data": "a"}, {"text": "B", "url": "https://..."}],
          [{"text": "Назад", "callback_data": "main_menu"}]
        ]

    Поля кнопки: ``text`` (обязательно), опционально ``callback_data`` или ``url`` (не оба пустые).
    """
    if not buttons_json:
        return None
    if not isinstance(buttons_json, list):
        logger.warning("buttons_json must be a list of rows, got %s", type(buttons_json))
        return None

    builder = InlineKeyboardBuilder()
    for row in buttons_json:
        if not isinstance(row, list):
            continue
        row_len = 0
        for btn in row:
            if not isinstance(btn, dict):
                continue
            text = (btn.get("text") or "").strip()
            if not text:
                continue
            cb = (btn.get("callback_data") or "").strip() or None
            url = (btn.get("url") or "").strip() or None
            if url:
                builder.button(text=text, url=url)
                row_len += 1
            elif cb:
                builder.button(text=text, callback_data=cb)
                row_len += 1
            else:
                logger.debug("skip button without callback_data/url: %r", btn)
        if row_len:
            builder.adjust(row_len)

    return builder.as_markup()
