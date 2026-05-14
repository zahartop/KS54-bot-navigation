"""Единая настройка HTTP-сессии aiogram для нестабильных сетей (Telegram Bot API)."""

from __future__ import annotations

import logging
import socket
import ssl
from typing import Any

import certifi
from aiogram.__meta__ import __version__ as aiogram_version
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from aiohttp.hdrs import USER_AGENT
from aiohttp.http import SERVER_SOFTWARE

from src.config.settings import Settings

logger = logging.getLogger(__name__)


class _TelegramAiohttpSession(AiohttpSession):
    """TCPConnector / SOCKS через родителя или HTTP(S)-прокси через ``ClientSession(proxy=...)``."""

    def __init__(
        self,
        proxy: Any = None,
        *,
        force_ipv4: bool = False,
        http_connect_proxy: str = "",
        limit: int = 100,
        **kwargs: Any,
    ) -> None:
        self._http_connect_proxy = (http_connect_proxy or "").strip()
        self._force_ipv4 = force_ipv4
        self._custom_limit = limit
        # HTTP CONNECT: не передаём proxy в super (иначе aiohttp-socks).
        super().__init__(proxy=None if self._http_connect_proxy else proxy, limit=limit, **kwargs)
        if not self._http_connect_proxy and force_ipv4:
            self._connector_init = {
                **self._connector_init,
                "family": socket.AF_INET,
                "happy_eyeballs_delay": None,
            }

    async def create_session(self) -> ClientSession:
        if self._http_connect_proxy:
            await self.close()
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            connector = TCPConnector(ssl=ssl_ctx, limit=self._custom_limit)
            self._session = ClientSession(
                connector=connector,
                proxy=self._http_connect_proxy,
                headers={
                    USER_AGENT: f"{SERVER_SOFTWARE} aiogram/{aiogram_version}",
                },
            )
            self._should_reset_connector = False
            logger.info("Telegram HTTP session: HTTP(S) proxy через ClientSession(proxy=...).")
            return self._session
        return await super().create_session()


def build_telegram_client_timeout(total_seconds: float) -> ClientTimeout:
    """Таймауты aiohttp: отдельно connect и sock_read (важно для long polling)."""

    t = max(60.0, float(total_seconds))
    connect = min(45.0, max(12.0, t * 0.2))
    sock_read = max(t, 90.0)
    total_cap = t + connect + 20.0
    return ClientTimeout(total=total_cap, connect=connect, sock_read=sock_read)


def create_bot_aiohttp_session(settings: Settings) -> AiohttpSession:
    total_seconds = float(max(30.0, settings.TELEGRAM_HTTP_TIMEOUT_SECONDS))
    client_timeout = build_telegram_client_timeout(total_seconds)
    proxy_raw = settings.TELEGRAM_PROXY.get_secret_value().strip()
    proxy = proxy_raw if proxy_raw else None
    http_proxy = settings.TELEGRAM_HTTP_CONNECT_PROXY.get_secret_value().strip()
    session = _TelegramAiohttpSession(
        proxy=proxy,
        timeout=client_timeout,
        force_ipv4=settings.TELEGRAM_FORCE_IPV4,
        http_connect_proxy=http_proxy,
    )
    session.timeout = client_timeout.total
    return session
