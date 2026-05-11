"""Общие утилиты для хендлеров: валидация, уведомления администраторам."""

from __future__ import annotations

import html
import logging
import re

from aiogram import Bot, types

from src.config.content import ADMIN_NEW_APPLICATION
from src.data.user_repository import UserRepository
from src.logic.abi.keyboards.kb import cancel_input_kb
from src.utils.pii import mask_pii

logger = logging.getLogger(__name__)

FIO_PATTERN = re.compile(
    r"^[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)*"
    r"(?:\s+[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)*)+$"
)
PHONE_PATTERN = re.compile(r"^(?:\+7\d{10}|8\d{10})$")

_TYPO_TLDS: frozenset[str] = frozenset({
    "con", "cmo", "ocm", "cpm", "cob", "om", "cm",
    "nt", "ne", "nrt", "og", "rg", "orgg", "ur", "ruu",
})


def is_valid_fio(fio: str) -> bool:
    return bool(FIO_PATTERN.fullmatch(fio))


def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_PATTERN.fullmatch(phone))


def is_valid_email(email: str) -> bool:
    if not email:
        return False
    try:
        from email_validator import EmailNotValidError, validate_email

        result = validate_email(email, check_deliverability=False)
        tld = result.ascii_domain.rsplit(".", 1)[-1].lower()
        return tld not in _TYPO_TLDS
    except EmailNotValidError:
        return False


async def extract_text(message: types.Message) -> str | None:
    if not message.text:
        await message.answer("Пожалуйста, введите текст", reply_markup=cancel_input_kb())
        return None
    return message.text.strip()


async def notify_admin(
    bot: Bot,
    user_repository: UserRepository,
    *,
    app_id: int,
    form_type: str,
    fio: str,
    detail: str,
) -> None:
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
            logger.warning("Не удалось отправить уведомление администратору: admin_tid=%s", admin_tid, exc_info=True)
