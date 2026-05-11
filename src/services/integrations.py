"""Абстрактный интерфейс и заглушка для будущих интеграций (Docflow, Kafka и т.п.)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class IntegrationService(ABC):
    """Контракт для внешних интеграций, вызываемых после регистрации."""

    @abstractmethod
    async def send_to_docflow(self, data: dict[str, Any]) -> bool:
        ...

    @abstractmethod
    async def send_to_kafka(self, data: dict[str, Any]) -> bool:
        ...


class StubIntegrationService(IntegrationService):
    """Заглушка: логирует вызов, но ничего не отправляет."""

    async def send_to_docflow(self, data: dict[str, Any]) -> bool:
        logger.info("[STUB] send_to_docflow: %s", data.get("kind", "?"))
        return True

    async def send_to_kafka(self, data: dict[str, Any]) -> bool:
        logger.info("[STUB] send_to_kafka: %s", data.get("kind", "?"))
        return True
