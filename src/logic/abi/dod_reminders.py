"""Напоминания о Дне открытых дверей (APScheduler, персистентность через job store)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from src.config.content import DOD_REMINDER_2H, DOD_REMINDER_24H
from src.config.settings import get_settings
from src.utils.date_tools import parse_user_date
from src.utils.telegram_session import create_bot_aiohttp_session

logger = logging.getLogger(__name__)

REMINDER_JOB_PREFIX = "dod_reminder"


def open_day_event_utc(date_str: str, hour_utc: int) -> datetime:
    """Дата из анкеты (как в БД) + фиксированный час начала события в UTC."""

    base = parse_user_date(date_str)
    d = base.date()
    return datetime(d.year, d.month, d.day, hour_utc, 0, 0, tzinfo=timezone.utc)


async def execute_dod_reminder(
    telegram_user_id: int,
    application_id: int,
    reminder_kind: str,
    event_date_label: str,
) -> None:
    """Вызывается планировщиком после рестарта: отдельный Bot-сессион, только примитивы в kwargs."""

    settings = get_settings()
    text = (
        DOD_REMINDER_24H.format(date=event_date_label)
        if reminder_kind == "24h"
        else DOD_REMINDER_2H.format(date=event_date_label)
    )
    bot = Bot(token=settings.BOT_TOKEN.get_secret_value().strip(), session=create_bot_aiohttp_session(settings))
    try:
        await bot.send_message(telegram_user_id, text, parse_mode="HTML")
        logger.info(
            "ДОД напоминание отправлено: user=%s app=%s kind=%s",
            telegram_user_id,
            application_id,
            reminder_kind,
        )
    except Exception:
        logger.exception(
            "ДОД напоминание не доставлено: user=%s app=%s kind=%s",
            telegram_user_id,
            application_id,
            reminder_kind,
        )
    finally:
        await bot.session.close()


def schedule_open_day_reminders(
    scheduler: AsyncIOScheduler,
    *,
    application_id: int,
    telegram_user_id: int,
    open_day_date: str,
) -> None:
    """Планирует «за 24 ч» и «за 2 ч» до условного начала ДОД; пропускает прошедшие слоты."""

    settings = get_settings()
    if not settings.OPEN_DAY_REMINDER_ENABLED:
        return

    event_at = open_day_event_utc(open_day_date, hour_utc=settings.OPEN_DAY_EVENT_HOUR_UTC)
    now = datetime.now(tz=timezone.utc)

    for kind, delta in (("24h", timedelta(hours=24)), ("2h", timedelta(hours=2))):
        run_at = event_at - delta
        job_id = f"{REMINDER_JOB_PREFIX}_{application_id}_{kind}"
        if run_at <= now:
            logger.info(
                "ДОД reminder пропуск (уже прошло): id=%s kind=%s run_at=%s",
                application_id,
                kind,
                run_at.isoformat(),
            )
            continue
        scheduler.add_job(
            "src.logic.abi.dod_reminders:execute_dod_reminder",
            trigger=DateTrigger(run_date=run_at),
            kwargs={
                "telegram_user_id": int(telegram_user_id),
                "application_id": int(application_id),
                "reminder_kind": kind,
                "event_date_label": open_day_date,
            },
            id=job_id,
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info(
            "ДОД reminder запланирован: app=%s kind=%s at=%s",
            application_id,
            kind,
            run_at.isoformat(),
        )


def cancel_open_day_reminders(scheduler: AsyncIOScheduler, application_id: int) -> None:
    """Удаляет обе задачи напоминаний для заявки (например, при отмене в будущем)."""

    for kind in ("24h", "2h"):
        job_id = f"{REMINDER_JOB_PREFIX}_{application_id}_{kind}"
        try:
            scheduler.remove_job(job_id, jobstore="default")
        except Exception:
            logger.warning("ДОД reminder: задача %s не удалена (возможно нет в планировщике).", job_id, exc_info=True)
