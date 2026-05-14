"""Pydantic-схемы событий шины (Kafka) для интеграции с Docflow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class EnrollmentEvent(BaseModel):
    """Событие в топик ``enrollment_updates``."""

    timestamp: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    user_id: int
    event_type: Literal["specialty_completed", "open_day_registered", "appeal_submitted"]
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_json_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")
