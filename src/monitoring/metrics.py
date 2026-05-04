"""In-memory счётчики без тяжёлых зависимостей (потокобезопасно)."""

from __future__ import annotations

import statistics
import threading
from collections import deque

_LOCK = threading.Lock()
_write_retries_since_watchdog: int = 0
_latency_recent_ms: deque[float] = deque(maxlen=36)


def record_db_write_retry() -> None:
    """Один неудачный цикл транзакции до следующей попытки (до лимита ретраев)."""

    global _write_retries_since_watchdog
    with _LOCK:
        _write_retries_since_watchdog += 1


def take_write_retries_and_reset() -> int:
    global _write_retries_since_watchdog
    with _LOCK:
        n = _write_retries_since_watchdog
        _write_retries_since_watchdog = 0
        return n


def record_watchdog_ping_ms(ms: float) -> None:
    with _LOCK:
        _latency_recent_ms.append(float(ms))


def previous_median_before_append() -> tuple[list[float], float | None]:
    """Снимок истории до добавления текущего замера."""

    with _LOCK:
        snap = list(_latency_recent_ms)
    if len(snap) < 2:
        return snap, None
    return snap, float(statistics.median(snap))
