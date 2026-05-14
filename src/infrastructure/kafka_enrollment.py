"""AIOKafka producer: публикация событий для Docflow."""

from __future__ import annotations

import logging

from aiokafka import AIOKafkaProducer

from src.application.schemas.enrollment_events import EnrollmentEvent
from src.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_global_producer: EnrollmentKafkaProducer | None = None


def set_global_kafka_producer(p: "EnrollmentKafkaProducer | None") -> None:
    """Устанавливается из ``main`` при старте процесса."""

    global _global_producer
    _global_producer = p


def get_kafka_producer() -> EnrollmentKafkaProducer | None:
    return _global_producer


class EnrollmentKafkaProducer:
    """Опциональный producer: при пустом ``KAFKA_BOOTSTRAP_SERVERS`` — no-op."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._producer: AIOKafkaProducer | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._settings.KAFKA_BOOTSTRAP_SERVERS.strip())

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Kafka: KAFKA_BOOTSTRAP_SERVERS пуст — producer выключен.")
            return
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._settings.KAFKA_BOOTSTRAP_SERVERS.strip(),
            client_id=self._settings.KAFKA_CLIENT_ID,
            compression_type="gzip",
        )
        await self._producer.start()
        logger.info("Kafka producer started: %s", self._settings.KAFKA_BOOTSTRAP_SERVERS)

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None
            logger.info("Kafka producer stopped.")

    @property
    def is_connected(self) -> bool:
        """True, если producer запущен и готов к отправке."""
        return self._producer is not None

    async def publish_enrollment(self, event: EnrollmentEvent) -> None:
        """Отправить JSON-событие в топик ``enrollment_updates``."""
        if self._producer is None:
            if self.enabled:
                logger.warning("Kafka producer not started, skip event_type=%s", event.event_type)
            return
        topic = self._settings.KAFKA_TOPIC_ENROLLMENT.strip() or "enrollment_updates"
        try:
            await self._producer.send_and_wait(topic, event.to_json_bytes())
        except Exception:
            logger.exception("Kafka send failed topic=%s event=%s", topic, event.event_type)
