"""Минимальный aiohttp-сервер: GET ``/healthz`` для probes (K8s / Docker HEALTHCHECK)."""

from __future__ import annotations

import json
import logging
import os

from aiohttp import web

from src.config.settings import Settings, get_settings
from src.monitoring.health_checks import check_database_ok, check_telegram_ok

logger = logging.getLogger(__name__)

_runner_site: tuple[web.AppRunner, web.BaseSite | None] | None = None


def build_health_app(settings: Settings, bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app["settings"] = settings
    app.router.add_get("/healthz", handle_health)
    app.router.add_get("/health", handle_health)
    return app


async def handle_health(request: web.Request) -> web.Response:
    bot = request.app["bot"]

    pg_ok, pg_detail = await check_database_ok()
    tg_ok, tg_detail = await check_telegram_ok(bot)
    overall = pg_ok and tg_ok
    payload = {
        "status": "healthy" if overall else "unhealthy",
        "postgres_ok": pg_ok,
        "postgres_detail": pg_detail or "",
        "telegram_ok": tg_ok,
        "telegram_detail": tg_detail or "",
    }
    raw = json.dumps(payload, ensure_ascii=False)
    return web.Response(
        text=raw,
        content_type="application/json",
        status=200 if overall else 503,
    )


async def start_health_http(settings: Settings, bot) -> None:
    """Поднимает HTTP если ``HEALTHCHECK_PORT > 0``."""

    global _runner_site

    port = getattr(settings, "HEALTHCHECK_PORT", 0) or 0
    if port <= 0:
        return

    fastapi_raw = os.environ.get("FASTAPI_PORT", "").strip()
    if fastapi_raw:
        try:
            fastapi_port = int(fastapi_raw)
        except ValueError:
            fastapi_port = int(get_settings().FASTAPI_PORT or 0)
    else:
        fastapi_port = int(get_settings().FASTAPI_PORT or 0)
    if fastapi_port > 0 and port == fastapi_port:
        logger.warning(
            "HEALTHCHECK_PORT=%s совпадает с FASTAPI_PORT — второй слушатель на том же порту не поднимаем.",
            port,
        )
        return

    host = getattr(settings, "HEALTHCHECK_HOST", "0.0.0.0")

    app = build_health_app(settings, bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    _runner_site = (runner, site)
    logger.info("Healthcheck HTTP listening on http://%s:%s/healthz", host, port)


async def stop_health_http() -> None:
    global _runner_site

    if _runner_site is None:
        return
    runner, _site = _runner_site
    _runner_site = None
    try:
        await runner.cleanup()
    except Exception:
        logger.exception("health HTTP cleanup")
