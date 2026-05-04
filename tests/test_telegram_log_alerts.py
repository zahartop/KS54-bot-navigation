"""Фильтры алертов ERROR → Telegram."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

from aiogram.exceptions import TelegramNetworkError
from src.monitoring.telegram_log_alerts import SkipTransientNetworkTelegramAlertFilter


def _record_with_exc(exc: Exception) -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="err",
        args=(),
        exc_info=(type(exc), exc, exc.__traceback__),
    )


def test_skip_transient_filter_blocks_telegram_network_error() -> None:
    flt = SkipTransientNetworkTelegramAlertFilter()
    exc = TelegramNetworkError(method=MagicMock(), message="connection reset")
    assert flt.filter(_record_with_exc(exc)) is False


def test_skip_transient_filter_blocks_timeout_error() -> None:
    flt = SkipTransientNetworkTelegramAlertFilter()
    exc = asyncio.TimeoutError()
    assert flt.filter(_record_with_exc(exc)) is False


def test_skip_transient_filter_blocks_when_skip_admin_flag() -> None:
    flt = SkipTransientNetworkTelegramAlertFilter()
    rec = logging.LogRecord(name="test", level=logging.ERROR, pathname="", lineno=0, msg="x", args=(), exc_info=None)
    rec.skip_admin_telegram = True
    assert flt.filter(rec) is False


def test_skip_transient_filter_allows_other_errors() -> None:
    flt = SkipTransientNetworkTelegramAlertFilter()
    exc = ValueError("logic")
    assert flt.filter(_record_with_exc(exc)) is True


def test_skip_transient_filter_allows_plain_error_log() -> None:
    flt = SkipTransientNetworkTelegramAlertFilter()
    rec = logging.LogRecord(name="test", level=logging.ERROR, pathname="", lineno=0, msg="x", args=(), exc_info=None)
    assert flt.filter(rec) is True
