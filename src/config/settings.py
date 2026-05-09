import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _running_in_docker() -> bool:
    return Path("/.dockerenv").exists()


class Settings(BaseSettings):
    BOT_TOKEN: SecretStr
    ADMIN_ID: int = Field(
        default=0,
        description="Telegram user id: лог-алерты, watchdog; при >0 также полный доступ к /admin (дублирует is_admin в БД).",
    )
    # Таймаут HTTP к api.telegram.org (сек). В Docker при «Request timeout» увеличьте до 120–180.
    TELEGRAM_HTTP_TIMEOUT_SECONDS: float = 120.0
    # Только IPv4 для aiohttp (VPS с «битым» IPv6: DNS отдаёт AAAA → таймаут get_me / polling).
    TELEGRAM_FORCE_IPV4: bool = False
    # SOCKS5/SOCKS4 или цепочка — см. aiogram + aiohttp-socks; для HTTP CONNECT подберите прокси с поддержкой HTTPS.
    TELEGRAM_PROXY: SecretStr = Field(default_factory=lambda: SecretStr(""))
    # Ретраи get_me при старте сессии (экспоненциальная пауза между попытками).
    TELEGRAM_STARTUP_MAX_ATTEMPTS: int = Field(default=8, ge=5, le=10)
    TELEGRAM_STARTUP_BACKOFF_INITIAL_SECONDS: float = Field(default=2.0, ge=0.5)
    TELEGRAM_STARTUP_BACKOFF_MAX_SECONDS: float = Field(default=120.0, ge=5.0)
    DATABASE_URL: SecretStr = Field(default_factory=lambda: SecretStr(""))
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = False
    POSTGRES_DB: str = "college_db"
    POSTGRES_USER: str = "user"
    POSTGRES_PASSWORD: SecretStr = SecretStr("password")
    DB_POOL_SIZE: int = 3
    DB_MAX_OVERFLOW: int = 7
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_CONNECT_TIMEOUT: int = 10
    DB_INIT_MAX_RETRIES: int = 10
    DB_INIT_RETRY_DELAY: int = 3
    DB_WRITE_MAX_RETRIES: int = 3
    DB_WRITE_RETRY_DELAY: int = 1
    DB_WRITE_TIMEOUT: int = 10
    # Self-healing: фоновый ping БД и пересборка пула при обрыве (0 = выкл.)
    DB_KEEPALIVE_INTERVAL_SECONDS: int = 60
    # Рассылка: жёсткий лимит времени задачи asyncio (0 = без лимита)
    BROADCAST_HARD_TIMEOUT_SECONDS: int = 3600
    # Супервизор: повтор запуска сессии опроса при фатальных ошибках
    BOT_SUPERVISOR_INITIAL_BACKOFF_SECONDS: float = 3.0
    BOT_SUPERVISOR_MAX_BACKOFF_SECONDS: float = 60.0
    BOT_SUPERVISOR_MAX_CONSECUTIVE_CRASHES: int = 0  # 0 = без ограничения попыток
    # Выгрузка CSV: таймаут на каждый запрос к репозиторию
    ADMIN_EXPORT_TIMEOUT_SECONDS: int = 120
    # Redis FSM — оставьте пустым для MemoryStorage (только для разработки)
    REDIS_HOST: str = ""
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    # Напоминания о ДОД (APScheduler → PostgreSQL job store при старте)
    OPEN_DAY_REMINDER_ENABLED: bool = True
    # Час начала события ДОД в UTC (день — из даты записи пользователя)
    OPEN_DAY_EVENT_HOUR_UTC: int = 10
    # Рассылки: сообщений в секунду (осторожный лимит ниже 30)
    BROADCAST_MAX_MESSAGES_PER_SECOND: float = 25.0
    # Мониторинг (лёгкий): HTTP liveness, алерты в TG при ERROR, почасовой watchdog
    # 0 — не поднимать HTTP-сервер
    HEALTHCHECK_PORT: int = 0
    HEALTHCHECK_HOST: str = "0.0.0.0"
    # Алерты из логгера (анти-спам)
    ALERT_TELEGRAM_MIN_INTERVAL_SECONDS: int = 120
    ALERT_TELEGRAM_MAX_PER_HOUR: int = 12
    ALERT_TELEGRAM_MAX_BODY_CHARS: int = 3500
    # Watchdog (раз в час): пороги «плохого самочувствия»
    WATCHDOG_INTERVAL_MINUTES: int = 60
    WATCHDOG_DB_LATENCY_WARN_MS: float = 800.0
    # Текущая латентность > max(база_мс, медиана_последних_проб * ratio)
    WATCHDOG_DB_LATENCY_SPIKE_RATIO: float = 2.5
    WATCHDOG_WRITE_RETRIES_WARN_PER_HOUR: int = 25

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _coerce_database_url_secret(cls, v: object) -> SecretStr:
        if isinstance(v, SecretStr):
            return v
        if v is None:
            return SecretStr("")
        return SecretStr(str(v))

    @model_validator(mode="after")
    def validate_required_values(self) -> "Settings":
        token = self.BOT_TOKEN.get_secret_value().strip()
        if not token:
            raise ValueError("BOT_TOKEN is empty")

        if not self.DATABASE_URL.get_secret_value().strip():
            if not self.POSTGRES_DB.strip():
                raise ValueError("POSTGRES_DB is empty")
            if not self.POSTGRES_USER.strip():
                raise ValueError("POSTGRES_USER is empty")
            if not self.POSTGRES_PASSWORD.get_secret_value().strip():
                raise ValueError("POSTGRES_PASSWORD is empty")
        return self

    @property
    def effective_database_url(self) -> str:
        """Строка подключения к PostgreSQL.

        В Docker Compose имя хоста БД — ``db``; в ``.env`` часто оставляют
        ``DATABASE_URL`` с ``localhost`` / ``127.0.0.1`` для Alembic на Mac.
        Внутри контейнера бота тогда ломается DNS или коннект — используем
        ``POSTGRES_*`` и хост ``db`` (как сервис ``db`` в compose).

        Обход (редко): ``DATABASE_USE_DOTENV_URL=1`` — брать ``DATABASE_URL`` и в Docker.
        """
        db_url = self.DATABASE_URL.get_secret_value().strip()
        if _running_in_docker():
            if os.environ.get("DATABASE_USE_DOTENV_URL") == "1" and db_url:
                return db_url
            host = os.environ.get("POSTGRES_HOST", "db")
            port = os.environ.get("POSTGRES_PORT", "5432")
            user = quote_plus(self.POSTGRES_USER)
            password = quote_plus(self.POSTGRES_PASSWORD.get_secret_value())
            db = quote_plus(self.POSTGRES_DB)
            return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"

        if db_url:
            return db_url

        password = quote_plus(self.POSTGRES_PASSWORD.get_secret_value())
        user = quote_plus(self.POSTGRES_USER)
        db = quote_plus(self.POSTGRES_DB)
        return f"postgresql+asyncpg://{user}:{password}@127.0.0.1:5432/{db}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise RuntimeError(
            "Configuration error: create `.env` with BOT_TOKEN and either DATABASE_URL "
            "or POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD. "
            "See `.env.example` for the full list of variables."
        ) from exc
