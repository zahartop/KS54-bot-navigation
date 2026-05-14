"""Сервис динамического контента: PostgreSQL + кэш Redis."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config.settings import Settings, get_settings
from src.data.models import BotContent

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "bot_content:v1:"


@dataclass(frozen=True)
class BotContentDTO:
    """DTO для экрана из БД."""

    slug: str
    text: str
    buttons: list[Any]


class ContentService:
    """Чтение ``bot_content`` с кэшированием в Redis (TTL из настроек)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings or get_settings()
        self._redis: Redis | None = None
        self._closed = False

    async def _get_redis(self) -> Redis | None:
        if not self._settings.REDIS_HOST.strip():
            return None
        if self._redis is None:
            url = f"redis://{self._settings.REDIS_HOST}:{self._settings.REDIS_PORT}/{self._settings.REDIS_DB}"
            self._redis = Redis.from_url(url, decode_responses=True)
        return self._redis

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    def _cache_key(self, slug: str) -> str:
        return f"{_CACHE_PREFIX}{slug}"

    async def invalidate(self, slug: str) -> None:
        r = await self._get_redis()
        if r is None:
            return
        try:
            await r.delete(self._cache_key(slug))
        except Exception:
            logger.debug("Redis invalidate failed for slug=%s", slug, exc_info=True)

    async def get_by_slug(self, slug: str) -> BotContentDTO | None:
        """Вернуть контент по slug или None."""
        r = await self._get_redis()
        ck = self._cache_key(slug)
        if r is not None:
            try:
                raw = await r.get(ck)
                if raw:
                    data = json.loads(raw)
                    return BotContentDTO(
                        slug=data["slug"],
                        text=data["text"],
                        buttons=data.get("buttons") or [],
                    )
            except Exception:
                logger.debug("Redis get failed slug=%s", slug, exc_info=True)

        async with self._session_factory() as session:
            row = await session.scalar(select(BotContent).where(BotContent.slug == slug))
            if row is None:
                return None
            dto = BotContentDTO(slug=row.slug, text=row.text, buttons=list(row.buttons or []))

        if r is not None:
            try:
                ttl = max(30, int(self._settings.CONTENT_CACHE_TTL_SECONDS))
                await r.set(
                    ck,
                    json.dumps({"slug": dto.slug, "text": dto.text, "buttons": dto.buttons}, ensure_ascii=False),
                    ex=ttl,
                )
            except Exception:
                logger.debug("Redis set failed slug=%s", slug, exc_info=True)

        return dto

    async def upsert(self, slug: str, text: str, buttons: list[Any]) -> None:
        """Создать или обновить запись (используется из FastAPI)."""
        async with self._session_factory() as session:
            row = await session.scalar(select(BotContent).where(BotContent.slug == slug))
            if row is None:
                session.add(BotContent(slug=slug, text=text, buttons=buttons))
            else:
                row.text = text
                row.buttons = buttons
            await session.commit()
        await self.invalidate(slug)
