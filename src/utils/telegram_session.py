"""Единая настройка HTTP-сессии aiogram для нестабильных сетей (Telegram Bot API)."""

from __future__ import annotations

import socket
from typing import Any

from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import ClientTimeout

from src.config.settings import Settings


class _TelegramAiohttpSession(AiohttpSession):
    """TCPConnector с опциональным family=AF_INET (обход сломанного IPv6 до api.telegram.org)."""

    def __init__(
        self,
        proxy: Any = None,
        *,
        force_ipv4: bool = False,
        limit: int = 100,
        **kwargs: Any,
    ) -> None:
        super().__init__(proxy=proxy, limit=limit, **kwargs)
        if force_ipv4:
            # family=AF_INET — только A-записи; happy_eyeballs_delay отключаем на всякий случай.
            self._connector_init = {
                **self._connector_init,
                "family": socket.AF_INET,
                "happy_eyeballs_delay": None,
            }


def build_telegram_client_timeout(total_seconds: float) -> ClientTimeout:
    """Таймауты aiohttp: отдельно connect и sock_read (важно для long polling)."""

    t = max(60.0, float(total_seconds))
    connect = min(45.0, max(12.0, t * 0.2))
    # Между чанками при getUpdates пауза может быть сравнима с полинг-таймаутом API.
    sock_read = max(t, 90.0)
    total_cap = t + connect + 20.0
    return ClientTimeout(total=total_cap, connect=connect, sock_read=sock_read)


def create_bot_aiohttp_session(settings: Settings) -> AiohttpSession:
    total_seconds = float(max(30.0, settings.TELEGRAM_HTTP_TIMEOUT_SECONDS))
    timeout = build_telegram_client_timeout(total_seconds)
    proxy_raw = settings.TELEGRAM_PROXY.get_secret_value().strip()
    proxy = proxy_raw if proxy_raw else None
    return _TelegramAiohttpSession(
        proxy=proxy,
        timeout=timeout,
        force_ipv4=settings.TELEGRAM_FORCE_IPV4,
    )
