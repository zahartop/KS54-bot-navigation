import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture()
def mock_bot() -> Bot:
    bot = AsyncMock(spec=Bot)
    bot.id = 123456789
    return bot


@pytest_asyncio.fixture()
async def state(storage: MemoryStorage, mock_bot: Bot) -> FSMContext:
    key = StorageKey(bot_id=mock_bot.id, chat_id=1, user_id=1)
    return FSMContext(storage=storage, key=key)


@pytest.fixture()
def user_repository() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def mock_message() -> AsyncMock:
    msg = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = 1
    msg.chat = MagicMock()
    msg.chat.id = 1
    msg.answer = AsyncMock()
    return msg


@pytest.fixture()
def mock_callback() -> AsyncMock:
    cb = AsyncMock()
    cb.from_user = MagicMock()
    cb.from_user.id = 1
    cb.message = AsyncMock()
    cb.message.chat = MagicMock()
    cb.message.chat.id = 1
    cb.answer = AsyncMock()
    cb.data = ""
    return cb
