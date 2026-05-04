"""Парсинг дат из пользовательского ввода (анкеты ДОД и т.п.) — вне слоя репозитория."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from src.utils.pii import mask_pii

logger = logging.getLogger(__name__)


def parse_user_date(value: str) -> datetime:
    """Разбор строки даты: ``DD.MM.YYYY``, ISO, «25 марта», «10 июня 2025»; иначе — сегодня UTC 00:00."""

    default_date = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    cleaned_value = value.strip().lower()

    russian_months = {
        "января": 1,
        "февраля": 2,
        "марта": 3,
        "апреля": 4,
        "мая": 5,
        "июня": 6,
        "июля": 7,
        "августа": 8,
        "сентября": 9,
        "октября": 10,
        "ноября": 11,
        "декабря": 12,
    }

    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned_value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    russian_date_match = re.fullmatch(r"(\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?", cleaned_value)
    if russian_date_match:
        day = int(russian_date_match.group(1))
        month_name = russian_date_match.group(2)
        year = int(russian_date_match.group(3)) if russian_date_match.group(3) else datetime.now(tz=timezone.utc).year
        month = russian_months.get(month_name)
        if month:
            try:
                return datetime(year=year, month=month, day=day, tzinfo=timezone.utc)
            except ValueError:
                logger.exception("Невалидная календарная дата: %s", mask_pii(value))

    logger.error(
        "Не удалось распарсить дату '%s'. Сохраняем дефолтную дату %s.",
        mask_pii(value),
        default_date.date(),
    )
    return default_date
