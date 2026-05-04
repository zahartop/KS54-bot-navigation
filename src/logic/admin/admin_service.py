"""Бизнес-логика админ-панели и рассылок: хендлеры вызывают сервис, не репозиторий напрямую."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config.content import (
    ADMIN_APPS_HEADER,
    ADMIN_BROADCAST_BTN,
    ADMIN_EXPORT_CAPTION,
    ADMIN_NO_NEW_APPS,
    ADMIN_STATS_TEMPLATE,
    ADMIN_STATUS_CHANGED,
    ADMIN_WELCOME,
    BROADCAST_DONE,
    BROADCAST_HARD_TIMEOUT_NOTICE,
    BROADCAST_RECOVERY_ERROR_NOTICE,
    STATUS_LABELS,
)
from src.config.settings import get_settings
from src.data.user_repository import UserRepository
from src.logic.admin.broadcast_service import run_broadcast_campaign
from src.utils.admin_guard import user_is_bot_admin

logger = logging.getLogger(__name__)


class AdminStatusCallback(CallbackData, prefix="adm_st"):
    app_type: str  # "od" (ДОД) | "sp" (специальность)
    app_id: int
    status: str  # "processed" | "declined"


@dataclass(frozen=True)
class AdminExportResult:
    filename: str
    file_bytes: bytes
    caption: str
    open_day: int
    specialty: int


@dataclass(frozen=True)
class ApplicationStatusUpdateResult:
    success: bool
    failure_alert: str | None
    success_answer: str | None
    body_text: str
    body_markup: InlineKeyboardMarkup


class AdminService:
    """Оркестрация админ-операций поверх :class:`UserRepository`."""

    def __init__(self, user_repository: UserRepository) -> None:
        self._repo = user_repository

    async def is_admin(self, telegram_user_id: int) -> bool:
        return await user_is_bot_admin(telegram_user_id, self._repo)

    def main_menu_markup(self) -> InlineKeyboardMarkup:
        return _admin_keyboard()

    def back_to_admin_markup(self) -> InlineKeyboardMarkup:
        return _back_to_admin_kb()

    def welcome_text(self) -> str:
        return ADMIN_WELCOME

    async def build_stats_screen(self) -> tuple[str, InlineKeyboardMarkup]:
        stats = await self._repo.get_stats()
        total = stats["open_day"] + stats["specialty"]
        text = ADMIN_STATS_TEMPLATE.format(
            open_day=stats["open_day"],
            specialty=stats["specialty"],
            consents=stats["consents"],
            total=total,
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="📋 Новые заявки", callback_data="admin_new_apps")
        builder.button(text="📥 Выгрузить CSV", callback_data="admin_export")
        builder.button(text=ADMIN_BROADCAST_BTN, callback_data="admin_broadcast")
        builder.button(text="🔄 Обновить", callback_data="admin_stats")
        builder.button(text="⬅️ Назад", callback_data="admin_back")
        builder.adjust(1)
        return text, builder.as_markup()

    async def build_new_apps_screen(self) -> tuple[str, InlineKeyboardMarkup]:
        apps = await self._repo.get_new_applications(limit=10)
        if not apps:
            return ADMIN_NO_NEW_APPS, _back_to_admin_kb()
        return _build_new_apps_view(apps)

    async def apply_application_status(
        self,
        *,
        app_type: str,
        app_id: int,
        status: str,
    ) -> ApplicationStatusUpdateResult:
        success = await self._repo.update_application_status(
            app_type=app_type,
            app_id=app_id,
            status=status,
        )
        if not success:
            return ApplicationStatusUpdateResult(
                success=False,
                failure_alert="❌ Не удалось изменить статус",
                success_answer=None,
                body_text="",
                body_markup=_back_to_admin_kb(),
            )

        status_label = STATUS_LABELS.get(status, status)
        success_answer = ADMIN_STATUS_CHANGED.format(app_id=app_id, status=status_label)

        apps = await self._repo.get_new_applications(limit=10)
        if not apps:
            body_text, body_markup = ADMIN_NO_NEW_APPS, _back_to_admin_kb()
        else:
            body_text, body_markup = _build_new_apps_view(apps)

        return ApplicationStatusUpdateResult(
            success=True,
            failure_alert=None,
            success_answer=success_answer,
            body_text=body_text,
            body_markup=body_markup,
        )

    async def build_export_package(self) -> AdminExportResult | None:
        """CSV за последние 30 дней или ``None``, если выгрузка пустая."""

        settings = get_settings()
        export_timeout = float(max(5, getattr(settings, "ADMIN_EXPORT_TIMEOUT_SECONDS", 120)))

        stats = await asyncio.wait_for(self._repo.get_stats(), timeout=export_timeout)
        csv_content = await asyncio.wait_for(self._repo.get_applications_csv(), timeout=export_timeout)

        if not csv_content.strip():
            return None

        filename = f"applications_{datetime.now(tz=timezone.utc).strftime('%Y-%m-%d')}.csv"
        file_bytes = ("\ufeff" + csv_content).encode("utf-8")
        caption = ADMIN_EXPORT_CAPTION.format(
            open_day=stats["open_day"],
            specialty=stats["specialty"],
            date=datetime.now(tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC"),
        )
        return AdminExportResult(
            filename=filename,
            file_bytes=file_bytes,
            caption=caption,
            open_day=stats["open_day"],
            specialty=stats["specialty"],
        )

    async def list_broadcast_recipient_ids_excluding_admins(self) -> list[int]:
        recipients = await self._repo.get_all_registered_telegram_user_ids()
        admin_ids = set(await self._repo.get_admin_telegram_user_ids())
        settings = get_settings()
        if settings.ADMIN_ID > 0:
            admin_ids.add(int(settings.ADMIN_ID))
        if admin_ids:
            return [r for r in recipients if r not in admin_ids]
        return recipients

    async def open_broadcast_recovery_job(
        self,
        admin_chat_id: int,
        *,
        payload_text: str | None,
        payload_photo_file_id: str | None,
        recipient_count: int,
    ) -> int | None:
        return await self._repo.open_broadcast_recovery_job(
            admin_chat_id,
            payload_text=payload_text,
            payload_photo_file_id=payload_photo_file_id,
            recipient_count=recipient_count,
        )

    async def get_broadcast_recovery_job(self, job_id: int) -> dict | None:
        return await self._repo.get_broadcast_recovery_job(job_id)

    async def set_broadcast_recovery_job_status(self, job_id: int, status: str) -> bool:
        return await self._repo.set_broadcast_recovery_job_status(job_id, status)

    async def finalize_broadcast_campaign(
        self,
        *,
        bot: Bot,
        notify_chat_id: int,
        recipient_ids: tuple[int, ...],
        text: str | None,
        photo_file_id: str | None,
        max_messages_per_second: float,
        recovery_job_id: int | None,
    ) -> None:
        settings = get_settings()
        hard_timeout = getattr(settings, "BROADCAST_HARD_TIMEOUT_SECONDS", 0) or 0

        async def _run_campaign() -> tuple[int, int]:
            return await run_broadcast_campaign(
                bot,
                recipient_ids=recipient_ids,
                text=text,
                photo_file_id=photo_file_id,
                max_messages_per_second=max_messages_per_second,
            )

        try:
            if hard_timeout > 0:
                ok, fail = await asyncio.wait_for(_run_campaign(), timeout=float(hard_timeout))
            else:
                ok, fail = await _run_campaign()
            if recovery_job_id is not None:
                await self._repo.set_broadcast_recovery_job_status(recovery_job_id, "completed")
            await bot.send_message(
                notify_chat_id,
                BROADCAST_DONE.format(ok=ok, fail=fail, total=len(recipient_ids)),
                parse_mode="HTML",
            )
        except asyncio.TimeoutError:
            logger.error("Рассылка: таймаут hard_timeout=%ss", hard_timeout)
            if recovery_job_id is not None:
                await self._repo.set_broadcast_recovery_job_status(recovery_job_id, "interrupted")
            try:
                await bot.send_message(
                    notify_chat_id,
                    BROADCAST_HARD_TIMEOUT_NOTICE,
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("Не удалось отправить уведомление о таймауте рассылки")
        except Exception:
            logger.exception("Рассылка: фатальная ошибка в фоне")
            try:
                await bot.send_message(
                    notify_chat_id,
                    BROADCAST_RECOVERY_ERROR_NOTICE,
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("Не удалось отправить уведомление об ошибке рассылки")


def _admin_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика за 30 дней", callback_data="admin_stats")
    builder.button(text="📋 Новые заявки", callback_data="admin_new_apps")
    builder.button(text="📥 Выгрузить CSV", callback_data="admin_export")
    builder.button(text=ADMIN_BROADCAST_BTN, callback_data="admin_broadcast")
    builder.adjust(1)
    return builder.as_markup()


def _back_to_admin_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="admin_back")
    return builder.as_markup()


def _build_new_apps_view(apps: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    text = ADMIN_APPS_HEADER.format(count=len(apps))
    builder = InlineKeyboardBuilder()

    type_emoji = {"od": "📅", "sp": "🎯"}
    for app in apps:
        emoji = type_emoji.get(app["type"], "📋")
        fio_short = app["fio"][:14] + "…" if len(app["fio"]) > 14 else app["fio"]
        text += f"{emoji} <b>№{app['id']}</b> {fio_short} — {app['detail']}\n"

        builder.row(
            InlineKeyboardButton(
                text=f"✅ №{app['id']}",
                callback_data=AdminStatusCallback(app_type=app["type"], app_id=app["id"], status="processed").pack(),
            ),
            InlineKeyboardButton(
                text=f"❌ Отказ №{app['id']}",
                callback_data=AdminStatusCallback(app_type=app["type"], app_id=app["id"], status="declined").pack(),
            ),
        )

    builder.row(InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_new_apps"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back"))

    return text, builder.as_markup()


def export_buffered_file(result: AdminExportResult) -> BufferedInputFile:
    return BufferedInputFile(result.file_bytes, filename=result.filename)
