"""Единая настройка HTTP-сессии aiogram для нестабильных сетей (Telegram Bot API)."""

from __future__ import annotations

from aiohttp import ClientTimeout
from aiogram.client.session.aiohttp import AiohttpSession


def build_telegram_client_timeout(total_seconds: float) -> ClientTimeout:
    """Таймауты aiohttp: отдельно connect и sock_read (важно для long polling)."""

    t = max(60.0, float(total_seconds))
    connect = min(45.0, max(12.0, t * 0.2))
    # Между чанками при getUpdates пауза может быть сравнима с полинг-таймаутом API.
    sock_read = max(t, 90.0)
    total_cap = t + connect + 20.0
    return ClientTimeout(total=total_cap, connect=connect, sock_read=sock_read)


def create_bot_aiohttp_session(total_seconds: float) -> AiohttpSession:
    return AiohttpSession(timeout=build_telegram_client_timeout(total_seconds))
