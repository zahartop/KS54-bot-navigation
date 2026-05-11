from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config.settings import get_settings
from src.utils.pii import mask_for_log

logger = logging.getLogger(__name__)


def _create_engine(settings) -> AsyncEngine:
    return create_async_engine(
        settings.effective_database_url,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        connect_args={"command_timeout": settings.DB_CONNECT_TIMEOUT},
    )


class DatabaseManager:
    """Инкапсулирует жизненный цикл AsyncEngine и session_factory."""

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._pool_repair_lock = asyncio.Lock()

    def _ensure_engine(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = _create_engine(get_settings())
        return self._engine

    def get_session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(self._ensure_engine(), expire_on_commit=False)
        return self._session_factory

    async def repair_pool(self) -> None:
        """Сброс пула (dispose) и создание нового engine/session_factory после обрыва с БД."""

        async with self._pool_repair_lock:
            logger.warning("PostgreSQL: пересборка пула соединений (dispose + новый engine).")
            engine = self._engine
            if engine is not None:
                try:
                    await engine.dispose()
                except Exception as exc:
                    logger.debug(
                        "engine.dispose завершился с ошибкой (игнорируем): %s",
                        mask_for_log(str(exc)),
                    )
            self._engine = None
            self._session_factory = None
            await asyncio.sleep(0.5)

            refreshed = self._ensure_engine()
            async with refreshed.connect() as conn:
                await conn.execute(text("SELECT 1"))

            factory = self.get_session_factory()
            async with factory() as session:
                await session.execute(text("SELECT 1"))
            logger.info("PostgreSQL: пул восстановлен, session_factory обновлён.")

    async def ping_or_repair(self) -> bool:
        """Проверка SELECT 1; при ошибке — repair_pool и повторная проверка."""

        settings = get_settings()
        timeout_sec = max(3.0, float(settings.DB_CONNECT_TIMEOUT))
        try:
            await asyncio.wait_for(self.measure_select_one_ms(), timeout=timeout_sec)
            return True
        except Exception as exc:
            logger.warning("PostgreSQL ping неуспешен: %s", mask_for_log(str(exc)))
            try:
                await self.repair_pool()
                await asyncio.wait_for(self.measure_select_one_ms(), timeout=timeout_sec)
                return True
            except Exception:
                logger.exception("PostgreSQL: не удалось восстановить пул после ping.")
                return False

    async def init_with_retry(self) -> None:
        settings = get_settings()
        min_wait = max(1.0, float(settings.DB_INIT_RETRY_DELAY))
        max_attempts = max(1, int(settings.DB_INIT_MAX_RETRIES))

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=1, min=min_wait, max=60.0),
                retry=retry_if_exception_type(SQLAlchemyError),
                reraise=True,
            ):
                with attempt:
                    try:
                        engine = self._ensure_engine()
                        async with engine.begin() as connection:
                            await connection.execute(text("SELECT 1"))
                        logger.info(
                            "Database connection verified (attempt %s).",
                            attempt.retry_state.attempt_number,
                        )
                        return
                    except SQLAlchemyError as exc:
                        logger.warning(
                            "Database init attempt %s/%s failed: %s",
                            attempt.retry_state.attempt_number,
                            max_attempts,
                            mask_for_log(str(exc)),
                        )
                        try:
                            await self.repair_pool()
                        except Exception as repair_exc:
                            logger.warning(
                                "repair_pool после неудачного init: %s",
                                mask_for_log(str(repair_exc)),
                            )
                        raise
        except SQLAlchemyError as last:
            raise RuntimeError("Failed to connect to database after retries.") from last

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
        self._engine = None
        self._session_factory = None

    async def measure_select_one_ms(self) -> float:
        """Среднее время простого ping к БД (мс), для мониторинга без тяжёлых ORM."""

        import time as time_module

        engine = self._ensure_engine()
        t0 = time_module.perf_counter()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        elapsed = time_module.perf_counter() - t0
        return elapsed * 1000.0


db_manager = DatabaseManager()
