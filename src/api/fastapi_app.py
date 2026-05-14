"""REST API (FastAPI): health, обновление контента из Docflow, выгрузка заявок."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, status
from prometheus_client import CollectorRegistry, Info
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from src.application.content_service import ContentService
from src.config.settings import Settings, get_settings
from src.data.user_repository import UserRepository
from src.infrastructure.kafka_enrollment import EnrollmentKafkaProducer
from src.monitoring.health_checks import check_database_ok

logger = logging.getLogger(__name__)


class ContentUpdateBody(BaseModel):
    """Тело POST для обновления экрана в ``bot_content``."""

    slug: str = Field(..., min_length=1, max_length=128)
    text: str = Field(default="", max_length=65535)
    buttons: list[list[dict[str, Any]]] = Field(default_factory=list)


def _verify_api_key(
    settings: Settings,
    x_api_key: str | None,
) -> None:
    secret = settings.API_SECRET.get_secret_value().strip()
    if not secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API_SECRET not configured")
    if not x_api_key or x_api_key.strip() != secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


async def _redis_ping(settings: Settings) -> tuple[bool, str]:
    if not settings.REDIS_HOST.strip():
        return True, "skipped (no REDIS_HOST)"
    url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    try:
        r = Redis.from_url(url, decode_responses=True)
        pong = await asyncio.wait_for(r.ping(), timeout=3.0)
        await r.aclose()
        return bool(pong), "pong"
    except Exception as exc:
        return False, str(exc)[:200]


def create_fastapi_app(
    *,
    user_repository: UserRepository,
    content_service: ContentService,
    kafka_producer: EnrollmentKafkaProducer,
) -> FastAPI:
    """Фабрика приложения FastAPI (запуск uvicorn отдельно от polling)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("FastAPI lifespan: started")
        yield
        await content_service.close()
        logger.info("FastAPI lifespan: content_service closed")

    app = FastAPI(title="College Bot API", version="1.0.0", lifespan=lifespan)

    # Отдельный registry на экземпляр приложения: при повторном create_fastapi_app
    # в том же процессе (supervisor) повторная регистрация в default REGISTRY даёт ValueError.
    metrics_registry = CollectorRegistry()
    Info(
        "college_bot_build",
        "Статичные метаданные процесса бота (Prometheus).",
        registry=metrics_registry,
    ).info({"app": "college-bot", "component": "fastapi"})

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/health", "/metrics"],
        registry=metrics_registry,
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Статус БД, Redis и Kafka (producer)."""
        settings = get_settings()
        db_ok, db_detail = await check_database_ok()
        redis_ok, redis_detail = await _redis_ping(settings)
        kafka_ok = True
        kafka_detail = "disabled"
        if kafka_producer.enabled:
            kafka_ok = kafka_producer.is_connected
            kafka_detail = "producer_ready" if kafka_ok else "producer_not_started"

        overall = db_ok and redis_ok and (kafka_ok or not kafka_producer.enabled)
        return {
            "status": "healthy" if overall else "unhealthy",
            "postgres_ok": db_ok,
            "postgres_detail": db_detail,
            "redis_ok": redis_ok,
            "redis_detail": redis_detail,
            "kafka_ok": kafka_ok if kafka_producer.enabled else True,
            "kafka_detail": kafka_detail,
        }

    @app.post("/api/v1/content/update")
    async def content_update(
        body: ContentUpdateBody,
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> dict[str, str]:
        """Обновить или создать запись ``bot_content`` (из Docflow / CMS)."""
        settings = get_settings()
        _verify_api_key(settings, x_api_key)
        await content_service.upsert(body.slug, body.text, body.buttons)
        return {"status": "ok", "slug": body.slug}

    @app.get("/api/v1/export/applications")
    async def export_applications(
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """JSON-выгрузка накопленных заявок (ДОД + специальности)."""
        settings = get_settings()
        _verify_api_key(settings, x_api_key)
        lim = max(1, min(limit, 20000))
        return await user_repository.export_applications_json(limit=lim)

    return app
