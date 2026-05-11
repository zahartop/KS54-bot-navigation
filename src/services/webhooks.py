"""Асинхронная отправка данных абитуриента на внешний webhook (n8n и т.п.)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class WebhookService:
    """Fire-and-forget POST на внешний URL. Ошибки логируются, но не блокируют пользователя."""

    def __init__(self, webhook_url: str, timeout_seconds: int = 10) -> None:
        self._url = webhook_url.strip()
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    async def send_application(self, data: dict[str, Any]) -> bool:
        if not self._url:
            return False
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(self._url, json=data) as resp:
                    ok = resp.status < 400
                    if not ok:
                        body = await resp.text()
                        logger.warning(
                            "Webhook returned %s: %s",
                            resp.status,
                            body[:500],
                        )
                    else:
                        logger.info("Webhook sent OK (%s)", resp.status)
                    return ok
        except asyncio.TimeoutError:
            logger.warning("Webhook timeout (%ss): %s", self._timeout.total, self._url)
            return False
        except Exception:
            logger.exception("Webhook error: %s", self._url)
            return False
