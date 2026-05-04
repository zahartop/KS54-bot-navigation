"""Рассылка из админки: FSM + фон через asyncio.create_task."""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router, types
from aiogram.enums import ContentType
from aiogram.filters import StateFilter, and_f, invert_f
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config.content import (
    BROADCAST_BTN_CANCEL,
    BROADCAST_BTN_SEND,
    BROADCAST_CANCELLED,
    BROADCAST_EMPTY_CONTENT,
    BROADCAST_NO_RECIPIENTS,
    BROADCAST_PREVIEW_INTRO,
    BROADCAST_PROMPT,
    BROADCAST_RECOVERY_CANCELLED,
    BROADCAST_RECOVERY_INVALID,
    BROADCAST_RECOVERY_RESUMED,
    BROADCAST_RESUME_DUP_WARNING,
    BROADCAST_STARTED,
)
from src.config.settings import get_settings
from src.data.user_repository import UserRepository
from src.logic.admin.admin_service import AdminService
from src.logic.admin.states.broadcast import BroadcastForm
from src.utils.admin_guard import user_is_bot_admin
from src.utils.safe_handler import safe_handler

router = Router(name="admin_broadcast")
logger = logging.getLogger(__name__)


def _parse_recovery_cancel(data: str) -> int | None:
    prefix = "recovery_bc_cancel:"
    if not data.startswith(prefix):
        return None
    try:
        return int(data[len(prefix) :])
    except ValueError:
        return None


def _preview_keyboard() -> types.InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text=BROADCAST_BTN_SEND, callback_data="broadcast_confirm_send"),
        InlineKeyboardButton(text=BROADCAST_BTN_CANCEL, callback_data="broadcast_abort"),
    )
    return b.as_markup()


@router.callback_query(F.data == "admin_broadcast")
@safe_handler
async def broadcast_start(
    callback: types.CallbackQuery,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    uid = callback.from_user.id if callback.from_user else 0
    if not await admin_service.is_admin(uid):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(BroadcastForm.composing)
    await callback.message.answer(BROADCAST_PROMPT, parse_mode="HTML")
    await callback.answer()


@router.message(StateFilter(BroadcastForm.composing), F.text.startswith("/"))
@safe_handler
async def broadcast_ignore_commands_while_compose(
    message: types.Message,
    state: FSMContext,
    admin_service: AdminService,
):
    """Команды в процессе составления не считаются контентом рассылки."""
    if not await admin_service.is_admin(message.from_user.id):
        await state.clear()
        return
    await message.answer("Сначала завершите или отмените рассылку (или /admin).")


@router.message(StateFilter(BroadcastForm.composing), F.content_type == ContentType.PHOTO)
@safe_handler
async def broadcast_take_photo(
    message: types.Message,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    if not await admin_service.is_admin(message.from_user.id):
        await state.clear()
        return

    fid = message.photo[-1].file_id if message.photo else ""
    cap = message.caption or ""
    await state.update_data(bf_photo_id=fid, bf_text=cap.strip())
    await state.set_state(BroadcastForm.preview)
    await message.answer(BROADCAST_PREVIEW_INTRO, parse_mode="HTML")
    await message.answer_photo(fid, caption=cap or None, parse_mode="HTML" if cap else None)
    await message.answer("Отправить?", reply_markup=_preview_keyboard())


@router.message(StateFilter(BroadcastForm.composing), F.content_type == ContentType.TEXT)
@safe_handler
async def broadcast_take_text(
    message: types.Message,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    if not await admin_service.is_admin(message.from_user.id):
        await state.clear()
        return
    body = message.text.strip() if message.text else ""
    if not body:
        await message.answer(BROADCAST_EMPTY_CONTENT)
        return

    await state.update_data(bf_photo_id="", bf_text=body)
    await state.set_state(BroadcastForm.preview)
    await message.answer(BROADCAST_PREVIEW_INTRO, parse_mode="HTML")
    await message.answer(body, parse_mode="HTML")
    await message.answer("Отправить?", reply_markup=_preview_keyboard())


@router.message(StateFilter(BroadcastForm.composing))
@safe_handler
async def broadcast_take_other(
    message: types.Message,
    state: FSMContext,
    user_repository: UserRepository,
):
    """Видео, стикеры и т.п. пока не поддерживаем.

    Явная проверка ``user_is_bot_admin`` (не только FSM): сбрасываем чужое состояние,
    если не-админ каким-то образом оказался в ``BroadcastForm.composing``.
    """
    uid = message.from_user.id if message.from_user else 0
    if not await user_is_bot_admin(uid, user_repository):
        await state.clear()
        return

    await message.answer(BROADCAST_EMPTY_CONTENT)


@router.callback_query(StateFilter(BroadcastForm.preview), F.data == "broadcast_abort")
@safe_handler
async def broadcast_abort(
    callback: types.CallbackQuery,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    uid = callback.from_user.id if callback.from_user else 0
    if not await admin_service.is_admin(uid):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.message.answer(BROADCAST_CANCELLED)
    await callback.answer()


@router.callback_query(StateFilter(BroadcastForm.preview), F.data == "broadcast_confirm_send")
@safe_handler
async def broadcast_confirm_send(
    callback: types.CallbackQuery,
    state: FSMContext,
    bot: types.Bot,
    admin_service: AdminService,
) -> None:
    uid = callback.from_user.id if callback.from_user else 0
    if not await admin_service.is_admin(uid):
        await callback.answer("Нет доступа", show_alert=True)
        return

    data = await state.get_data()
    text_piece = data.get("bf_text") or ""
    photo_id = data.get("bf_photo_id") or ""

    recipients = await admin_service.list_broadcast_recipient_ids_excluding_admins()

    if not recipients:
        await callback.message.answer(BROADCAST_NO_RECIPIENTS)
        await state.clear()
        await callback.answer()
        return

    if not photo_id and not text_piece.strip():
        await callback.message.answer(BROADCAST_EMPTY_CONTENT)
        await state.clear()
        await callback.answer()
        return

    settings = get_settings()
    rate = settings.BROADCAST_MAX_MESSAGES_PER_SECOND
    msg_admin = getattr(callback.message, "chat", None)
    admin_chat = msg_admin.id if msg_admin else uid

    await state.clear()
    recovery_job_id = await admin_service.open_broadcast_recovery_job(
        admin_chat,
        payload_text=text_piece if text_piece else None,
        payload_photo_file_id=photo_id if photo_id else None,
        recipient_count=len(recipients),
    )
    if recovery_job_id is None:
        logger.error("Не удалось создать broadcast_recovery_jobs для chat_id=%s", admin_chat)

    asyncio.create_task(
        admin_service.finalize_broadcast_campaign(
            bot=bot,
            notify_chat_id=admin_chat,
            recipient_ids=tuple(recipients),
            text=text_piece if text_piece else None,
            photo_file_id=photo_id if photo_id else None,
            max_messages_per_second=rate,
            recovery_job_id=recovery_job_id,
        ),
        name=f"broadcast_{admin_chat}",
    )
    await callback.message.answer(BROADCAST_STARTED.format(rate=rate), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("recovery_bc_cancel:"))
@safe_handler
async def broadcast_recovery_cancel(
    callback: types.CallbackQuery,
    admin_service: AdminService,
) -> None:
    uid = callback.from_user.id if callback.from_user else 0
    if not await admin_service.is_admin(uid):
        await callback.answer("Нет доступа", show_alert=True)
        return
    jid = _parse_recovery_cancel(callback.data or "")
    if jid is None:
        await callback.answer(BROADCAST_RECOVERY_INVALID, show_alert=True)
        return
    ok = await admin_service.set_broadcast_recovery_job_status(jid, "cancelled")
    if ok and callback.message:
        await callback.message.answer(BROADCAST_RECOVERY_CANCELLED.format(job_id=jid))
    elif callback.message:
        await callback.message.answer(BROADCAST_RECOVERY_INVALID)
    await callback.answer()


@router.callback_query(and_f(F.data.startswith("recovery_bc:"), invert_f(F.data.startswith("recovery_bc_cancel:"))))
@safe_handler
async def broadcast_recovery_resume(
    callback: types.CallbackQuery,
    bot: types.Bot,
    admin_service: AdminService,
) -> None:
    uid = callback.from_user.id if callback.from_user else 0
    if not await admin_service.is_admin(uid):
        await callback.answer("Нет доступа", show_alert=True)
        return

    raw = callback.data or ""
    prefix = "recovery_bc:"
    suffix = raw[len(prefix) :] if raw.startswith(prefix) else ""
    try:
        job_id = int(suffix)
    except ValueError:
        await callback.answer(BROADCAST_RECOVERY_INVALID, show_alert=True)
        return

    job = await admin_service.get_broadcast_recovery_job(job_id)
    if job is None or job["status"] not in {"active", "interrupted"}:
        await callback.answer(BROADCAST_RECOVERY_INVALID, show_alert=True)
        return

    recipients = await admin_service.list_broadcast_recipient_ids_excluding_admins()
    if not recipients:
        await callback.answer(BROADCAST_NO_RECIPIENTS, show_alert=True)
        return

    text_piece = (job.get("payload_text") or "").strip() or None
    photo_id = job.get("payload_photo_file_id") or ""
    photo_id = photo_id.strip() if photo_id else ""

    if not photo_id and not (text_piece and text_piece.strip()):
        await callback.answer(BROADCAST_EMPTY_CONTENT, show_alert=True)
        return

    await admin_service.set_broadcast_recovery_job_status(job_id, "active")
    settings = get_settings()
    rate = settings.BROADCAST_MAX_MESSAGES_PER_SECOND
    msg_admin = getattr(callback.message, "chat", None)
    admin_chat = msg_admin.id if msg_admin else uid

    asyncio.create_task(
        admin_service.finalize_broadcast_campaign(
            bot=bot,
            notify_chat_id=admin_chat,
            recipient_ids=tuple(recipients),
            text=text_piece,
            photo_file_id=photo_id if photo_id else None,
            max_messages_per_second=rate,
            recovery_job_id=job_id,
        ),
        name=f"broadcast_resume_{job_id}_{admin_chat}",
    )
    if callback.message:
        await callback.message.answer(
            BROADCAST_RECOVERY_RESUMED.format(job_id=job_id, rate=rate) + BROADCAST_RESUME_DUP_WARNING,
            parse_mode="HTML",
        )
    await callback.answer()
