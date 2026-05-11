import asyncio
import html
import logging
import sys
from logging.handlers import RotatingFileHandler
from os import path
from pathlib import Path

current_dir = path.dirname(path.abspath(__file__))
project_root = path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramNetworkError, TelegramServerError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent
from apscheduler.triggers.interval import IntervalTrigger
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config.settings import Settings, get_settings
from src.data.database import db_manager
from src.data.user_repository import UserRepository
from src.logic.abi.education_router import router as education_router
from src.logic.abi.handlers.consent_handler import router as consent_router
from src.logic.abi.handlers.menu_handler import router as menu_router
from src.logic.abi.handlers.open_day_handler import router as open_day_router
from src.logic.abi.handlers.specialty_handler import router as specialty_router
from src.logic.abi.handlers.survey_handler import router as survey_router
from src.logic.admin.admin_broadcast_handler import router as admin_broadcast_router
from src.logic.admin.admin_handler import router as admin_router
from src.logic.admin.admin_service import AdminService
from src.logic.admin.broadcast_recovery_notify import notify_pending_broadcast_jobs
from src.middlewares.access_control import AccessControlMiddleware
from src.middlewares.policy_pdn_consent import PolicyPdnConsentMiddleware
from src.middlewares.throttling import ThrottlingMiddleware
from src.monitoring.health_checks import assert_startup_health
from src.monitoring.health_server import start_health_http, stop_health_http
from src.monitoring.telegram_log_alerts import (
    attach_admin_telegram_log_handler,
    set_alert_event_loop,
    start_alert_consumer_task,
)
from src.services.integrations import StubIntegrationService
from src.services.scheduler_factory import build_async_scheduler
from src.services.webhooks import WebhookService
from src.utils.pii import PIIMaskingFilter, mask_for_log
from src.utils.telegram_session import create_bot_aiohttp_session


def setup_logging(level_name: str) -> None:
    logs_dir = Path(project_root) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "bot.log"

    handlers = [
        RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ]
    pii_filter = PIIMaskingFilter()
    for handler in handlers:
        handler.addFilter(pii_filter)

    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


setup_logging(get_settings().LOG_LEVEL)
logger = logging.getLogger(__name__)


def _create_fsm_storage(settings: Settings) -> MemoryStorage:
    """RedisStorage если REDIS_HOST задан, иначе MemoryStorage."""
    if not settings.REDIS_HOST:
        logger.info("FSM: MemoryStorage (для prod укажите REDIS_HOST в .env)")
        return MemoryStorage()
    try:
        from aiogram.fsm.storage.redis import RedisStorage

        url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
        storage = RedisStorage.from_url(url)
        logger.info(
            "FSM: RedisStorage подключён (%s:%s/db%s)",
            settings.REDIS_HOST,
            settings.REDIS_PORT,
            settings.REDIS_DB,
        )
        return storage
    except ImportError:
        logger.warning("FSM: пакет redis не установлен — используем MemoryStorage. Установите: pip install redis")
        return MemoryStorage()


async def _db_keepalive_loop(interval_seconds: float) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        ok = await db_manager.ping_or_repair()
        if not ok:
            logger.error("DB keepalive: пул восстановить не удалось — следующая попытка по интервалу.")


async def _delete_webhook_with_retry(bot: Bot) -> None:
    """Сетевые сбои Telegram на delete_webhook — до 5 попыток с растущей паузой."""

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((TelegramNetworkError, asyncio.TimeoutError)),
        reraise=True,
    ):
        with attempt:
            await bot.delete_webhook(drop_pending_updates=True)


async def _dispatch_error_logged(event: ErrorEvent, bot: Bot) -> bool:
    """Логирование всех ошибок; в личку ADMIN_ID — только ответы Telegram 5xx (без сетевых таймаутов)."""

    exc = event.exception
    exc_info_tuple = (type(exc), exc, exc.__traceback__)
    settings = get_settings()
    admin_id = settings.ADMIN_ID

    if isinstance(exc, (TelegramNetworkError, asyncio.TimeoutError)):
        logger.warning(
            "Исключение в хендлере (сетевой/таймаут, без TG-алерта): %s",
            exc,
            exc_info=exc_info_tuple,
        )
    elif isinstance(exc, TelegramServerError) and admin_id > 0:
        try:
            body = html.escape(mask_for_log(str(exc))[:3500])
            await bot.send_message(
                admin_id,
                f"⚠️ <b>Критично: Telegram 5xx</b>\n<pre>{body}</pre>",
                parse_mode="HTML",
            )
        except Exception:
            logger.debug("DM админу о TelegramServerError не отправлен", exc_info=True)
        logger.error(
            "Необработанное исключение в хендлере (Telegram 5xx): %s",
            exc,
            exc_info=exc_info_tuple,
            extra={"skip_admin_telegram": True},
        )
    else:
        logger.error(
            "Необработанное исключение в хендлере: %s",
            exc,
            exc_info=exc_info_tuple,
        )
    return True


def _detach_routers_from_dispatcher(dp: Dispatcher, routers: tuple[Router, ...]) -> None:
    """Снять вложенные роутеры с диспетчера (для повторного запуска supervised_main без «already attached»)."""

    for r in routers:
        if getattr(r, "parent_router", None) is not dp:
            continue
        try:
            dp.sub_routers.remove(r)
        except ValueError:
            logger.debug("Роутер %s не найден среди sub_routers диспетчера (пропуск при detach).", r.name)
        setattr(r, "_parent_router", None)


async def _run_single_bot_session() -> None:
    loop = asyncio.get_running_loop()
    set_alert_event_loop(loop)

    settings = get_settings()
    token = settings.BOT_TOKEN.get_secret_value().strip()
    logger.info(
        "Telegram client: TELEGRAM_FORCE_IPV4=%s, TELEGRAM_PROXY=%s",
        settings.TELEGRAM_FORCE_IPV4,
        "yes" if settings.TELEGRAM_PROXY.get_secret_value().strip() else "no",
    )
    bot = Bot(token=token, session=create_bot_aiohttp_session(settings))

    alert_task = start_alert_consumer_task(bot)
    attach_admin_telegram_log_handler()

    storage = _create_fsm_storage(settings)
    dp = Dispatcher(storage=storage)
    user_repository = UserRepository(
        lambda: db_manager.get_session_factory(),
        write_max_retries=settings.DB_WRITE_MAX_RETRIES,
        write_retry_delay_seconds=settings.DB_WRITE_RETRY_DELAY,
        write_timeout_seconds=settings.DB_WRITE_TIMEOUT,
    )
    dp["user_repository"] = user_repository
    dp["admin_service"] = AdminService(user_repository)
    dp["webhook_service"] = WebhookService(
        settings.N8N_WEBHOOK_URL,
        timeout_seconds=settings.N8N_WEBHOOK_TIMEOUT_SECONDS,
    )
    dp["integration_service"] = StubIntegrationService()
    policy_pdn_consent_mw = PolicyPdnConsentMiddleware()
    dp.message.middleware(policy_pdn_consent_mw)
    dp.callback_query.middleware(policy_pdn_consent_mw)
    dp.update.middleware(AccessControlMiddleware(user_repository))
    dp.update.middleware(ThrottlingMiddleware(ttl=0.3))
    scheduler = build_async_scheduler(settings)
    dp["scheduler"] = scheduler

    _included = (
        admin_broadcast_router, admin_router, education_router,
        consent_router, open_day_router, specialty_router,
        survey_router, menu_router,
    )
    dp.include_router(admin_broadcast_router)
    dp.include_router(admin_router)
    dp.include_router(education_router)
    dp.include_router(consent_router)
    dp.include_router(open_day_router)
    dp.include_router(specialty_router)
    dp.include_router(survey_router)
    dp.include_router(menu_router)

    dp.errors.register(_dispatch_error_logged)

    ka_interval_raw = getattr(settings, "DB_KEEPALIVE_INTERVAL_SECONDS", 0) or 0
    keepalive_task: asyncio.Task[None] | None = None
    watchdog_minutes = max(5, getattr(settings, "WATCHDOG_INTERVAL_MINUTES", 60))
    scheduler_started = False

    try:
        await db_manager.init_with_retry()
        await assert_startup_health(bot)

        scheduler.add_job(
            "src.monitoring.watchdog_job:run_health_watchdog",
            trigger=IntervalTrigger(minutes=watchdog_minutes),
            id="watchdog_health_watchdog",
            replace_existing=True,
            misfire_grace_time=300,
        )

        scheduler.start()
        scheduler_started = True
        logger.info("Бот успешно подключен к PostgreSQL. Режим: Prod-ready")
        logger.info("APScheduler запущен (ДОД + watchdog). Лог → TG при ERROR включён.")

        await start_health_http(settings, bot)

        if ka_interval_raw > 0:
            ka_iv = float(max(10, ka_interval_raw))
            keepalive_task = asyncio.create_task(_db_keepalive_loop(ka_iv), name="db_keepalive")
            logger.info("DB keepalive: интервал ping/repair %.0f с", ka_iv)

        await notify_pending_broadcast_jobs(bot, dp["user_repository"])

        logger.info("Запуск бота...")
        await _delete_webhook_with_retry(bot)
        await dp.start_polling(bot)
    finally:
        if keepalive_task is not None:
            keepalive_task.cancel()
            try:
                await keepalive_task
            except asyncio.CancelledError:
                logger.debug("DB keepalive: задача отменена при остановке.")

        alert_task.cancel()
        try:
            await alert_task
        except asyncio.CancelledError:
            logger.debug("Alert consumer: задача отменена при остановке.")

        await stop_health_http()
        if scheduler_started:
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                logger.exception("Ошибка остановки APScheduler")
        _detach_routers_from_dispatcher(dp, _included)
        await db_manager.close()
        await bot.session.close()
        logger.info("Бот остановлен (сессия опроса).")


async def supervised_main() -> None:
    settings = get_settings()
    backoff = float(max(1.0, settings.BOT_SUPERVISOR_INITIAL_BACKOFF_SECONDS))
    max_backoff = float(max(backoff, settings.BOT_SUPERVISOR_MAX_BACKOFF_SECONDS))
    max_consecutive = settings.BOT_SUPERVISOR_MAX_CONSECUTIVE_CRASHES
    consecutive = 0
    delay = backoff

    while True:
        try:
            await _run_single_bot_session()
            logger.info("Сессия бота завершилась без непойманных исключений.")
            return
        except (KeyboardInterrupt, SystemExit):
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive += 1
            logger.exception("Сессия бота завершилась с ошибкой.")
            _maybe_give_up(consecutive, max_consecutive)
            logger.warning("Перезапуск сессии через %.1f с (ошибок подряд: %s).", delay, consecutive)
            await asyncio.sleep(delay)
            delay = min(delay * 2.0, max_backoff)


def _maybe_give_up(consecutive: int, max_consecutive: int) -> None:
    if max_consecutive > 0 and consecutive >= max_consecutive:
        raise RuntimeError(
            f"Превышен лимит подряд идущих падений сессии бота ({max_consecutive}). Проверьте логи и конфигурацию."
        )


if __name__ == "__main__":
    try:
        asyncio.run(supervised_main())
    except RuntimeError as exc:
        logger.critical(str(exc))
        raise SystemExit(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Работа завершена.")
