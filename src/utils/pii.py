from __future__ import annotations

import logging
import re
import traceback

_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+\-])([A-Za-z0-9._%+\-]{0,63})@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
_PHONE_RE = re.compile(r"(?<!\d)(\+7\d{10}|8\d{10})(?!\d)")
_FIO_RE = re.compile(
    r"\b([A-ZА-ЯЁ][a-zа-яё]+(?:-[A-ZА-ЯЁ][a-zа-яё]+)*"
    r"(?:\s+[A-ZА-ЯЁ][a-zа-яё]+(?:-[A-ZА-ЯЁ][a-zа-яё]+)*)+)\b"
)
# protocol://user:password@host — маскируем только пароль (строки подключения, DSN в ошибках)
_CONN_URL_CREDS_RE = re.compile(
    r"(?P<scheme>[\w+.-]+://)(?P<user>[^/\s?#@]+):(?P<pwd>[^/\s?#@]+)@",
    re.UNICODE,
)


def _mask_email_match(match: re.Match[str]) -> str:
    first_char = match.group(1)
    domain = match.group(3)
    return f"{first_char}*******@{domain}"


def _mask_phone_match(match: re.Match[str]) -> str:
    phone = match.group(1)
    if phone.startswith("+7"):
        return f"+7*******{phone[-3:]}"
    return f"8*******{phone[-3:]}"


def _mask_fio_match(match: re.Match[str]) -> str:
    fio = match.group(1).strip()
    parts = [part for part in fio.split() if part]
    if len(parts) < 2:
        return fio
    surname_masked = f"{parts[0][0].upper()}*****"
    initials = ".".join(part[0].upper() for part in parts[1:]) + "."
    return f"{surname_masked} {initials}"


def _mask_connection_url_credentials(text: str) -> str:
    def _repl(m: re.Match[str]) -> str:
        return f"{m.group('scheme')}{m.group('user')}:***@"

    return _CONN_URL_CREDS_RE.sub(_repl, text)


def mask_pii(text: str) -> str:
    """Маскирует ПДн, учётные данные в URL подключения и стандартные паттерны в одной строке."""
    masked = _mask_connection_url_credentials(text)
    masked = _EMAIL_RE.sub(_mask_email_match, masked)
    masked = _PHONE_RE.sub(_mask_phone_match, masked)
    masked = _FIO_RE.sub(_mask_fio_match, masked)
    return masked


def mask_for_log(text: str) -> str:
    """Текст исключения / сообщения перед записью в лог (явная защита поверх PIIMaskingFilter)."""
    return mask_pii(text)


class PIIMaskingFilter(logging.Filter):
    """
    Маскирует ПДн (email, телефон, ФИО), пароли в connection strings (URL) во всех частях лог-записи:
    - record.msg (основное сообщение)
    - record.exc_info → конвертируется в замаскированный exc_text
    - record.exc_text (уже отформатированный traceback)
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # 1. Маскируем основное сообщение
        record.msg = mask_pii(record.getMessage())
        record.args = ()

        # 2. Маскируем traceback через exc_info (самый опасный вектор утечки):
        #    logger.exception(...) устанавливает exc_info=(type, value, tb).
        #    Стандартный форматтер рендерит traceback отдельно, наш фильтр его не видит.
        #    Решение: принудительно форматируем traceback здесь, маскируем и кладём
        #    в exc_text, а exc_info обнуляем чтобы форматтер не рендерил заново.
        if record.exc_info:
            raw_tb = "".join(traceback.format_exception(*record.exc_info))
            record.exc_text = mask_pii(raw_tb)
            record.exc_info = None

        # 3. Маскируем уже готовый exc_text (если пришёл из другого источника)
        elif record.exc_text:
            record.exc_text = mask_pii(record.exc_text)

        return True
