"""Контекстные менеджеры для сессий SQLAlchemy Async (PostgreSQL).

Использовать только внутри репозитория; хендлеры не должны открывать сессии вручную.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@asynccontextmanager
async def transactional_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Открывает сессию и **явную транзакцию** (BEGIN … COMMIT / ROLLBACK).

    При исключении внутри блока транзакция откатывается, сессия корректно закрывается.
    """

    async with session_factory() as session:
        async with session.begin():
            yield session


@asynccontextmanager
async def read_only_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Сессия для чтения без явной транзакции записи."""

    async with session_factory() as session:
        yield session
