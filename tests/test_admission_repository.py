import asyncio
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError
from src.data.admission_repository import AdmissionRepository
from src.utils.date_tools import parse_user_date


def test_parse_date_supports_dot_format() -> None:
    parsed = parse_user_date("25.03.2026")
    assert parsed == datetime(2026, 3, 25, tzinfo=timezone.utc)


def test_parse_date_supports_iso_format() -> None:
    parsed = parse_user_date("2026-06-10")
    assert parsed == datetime(2026, 6, 10, tzinfo=timezone.utc)


def test_parse_date_supports_russian_month_without_year() -> None:
    current_year = datetime.now(tz=timezone.utc).year
    parsed = parse_user_date("25 марта")
    assert parsed == datetime(current_year, 3, 25, tzinfo=timezone.utc)


def test_parse_date_supports_russian_month_with_year() -> None:
    parsed = parse_user_date("10 июня 2025")
    assert parsed == datetime(2025, 6, 10, tzinfo=timezone.utc)


def test_parse_date_returns_fallback_for_unparseable_value() -> None:
    parsed = parse_user_date("не дата")
    expected = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    assert parsed == expected


def test_parse_date_returns_fallback_for_invalid_calendar_date() -> None:
    parsed = parse_user_date("31 февраля")
    expected = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    assert parsed == expected


class _DummyBegin:
    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
        return False


class _DummySession:
    def begin(self):  # type: ignore[no-untyped-def]
        return _DummyBegin()

    async def commit(self) -> None:
        return None


class _DummySessionContext:
    def __init__(self) -> None:
        self.session = _DummySession()

    async def __aenter__(self) -> _DummySession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def _dummy_session_factory() -> _DummySessionContext:
    return _DummySessionContext()


def test_execute_with_retry_uses_exponential_backoff_and_max_three_attempts(monkeypatch) -> None:
    repository = AdmissionRepository(
        lambda: _dummy_session_factory,
        write_max_retries=10,
        write_retry_delay_seconds=1,
    )
    observed_delays: list[int] = []
    attempts = {"count": 0}

    async def fake_sleep(delay: int) -> None:
        observed_delays.append(delay)

    async def always_fail_operation(_session) -> None:
        attempts["count"] += 1
        raise SQLAlchemyError("db down")

    monkeypatch.setattr("src.data.user_repository.asyncio.sleep", fake_sleep)

    result = asyncio.run(repository._execute_with_retry(always_fail_operation, "Ошибка записи в БД"))

    assert result is False
    assert repository._write_max_retries == 3
    assert attempts["count"] == 3
    # С jitter ±10% задержки лежат в диапазонах [1.0, 1.1] и [2.0, 2.2]
    assert len(observed_delays) == 2
    assert 1.0 <= observed_delays[0] <= 1.1
    assert 2.0 <= observed_delays[1] <= 2.2


def test_execute_with_retry_returns_true_when_eventually_successful(monkeypatch) -> None:
    repository = AdmissionRepository(
        lambda: _dummy_session_factory,
        write_max_retries=3,
        write_retry_delay_seconds=1,
    )
    observed_delays: list[int] = []
    attempts = {"count": 0}

    async def fake_sleep(delay: int) -> None:
        observed_delays.append(delay)

    async def flaky_operation(_session) -> None:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise SQLAlchemyError("temporary error")

    monkeypatch.setattr("src.data.user_repository.asyncio.sleep", fake_sleep)

    result = asyncio.run(repository._execute_with_retry(flaky_operation, "Ошибка записи в БД"))

    assert result is True
    assert attempts["count"] == 3
    # С jitter ±10% задержки лежат в диапазонах [1.0, 1.1] и [2.0, 2.2]
    assert len(observed_delays) == 2
    assert 1.0 <= observed_delays[0] <= 1.1
    assert 2.0 <= observed_delays[1] <= 2.2
