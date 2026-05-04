# Развёртывание College Bot

Краткая инструкция для запуска с нуля в Docker.

## 1. Подготовка

1. Скопируйте переменные окружения: `cp .env.example .env`.
2. Заполните обязательные значения: **`BOT_TOKEN`**, **`POSTGRES_*`** (или `DATABASE_URL` для локального Alembic на хосте).

## 2. Запуск

Из каталога с `docker-compose.yml`:

```bash
docker compose build --no-cache
docker compose up -d
```

Сервис **`bot`** ждёт готовности **`db`** и **`redis`** (`depends_on` + `condition: service_healthy`). У контейнера бота включён **`restart: unless-stopped`**.

## 3. Миграции Alembic

При старте контейнера **`docker-entrypoint.sh`** выполняет `alembic upgrade head` перед запуском процесса бота.

Вручную (например после обновления образа):

```bash
docker compose exec bot alembic upgrade head
```

## 4. Логи

```bash
docker compose logs -f bot
```

Файловые логи приложения монтируются в volume **`bot_logs`** (`/app/logs/bot.log` внутри контейнера).

## 5. Полезные переменные сети и БД

- **`TELEGRAM_HTTP_TIMEOUT_SECONDS`** — таймаут HTTP к Telegram (рекомендуется 120–180 при нестабильной сети).
- **`TELEGRAM_STARTUP_MAX_ATTEMPTS`** (5–10) и **`TELEGRAM_STARTUP_BACKOFF_*`** — ретраи `get_me` при старте.
- **`DB_INIT_MAX_RETRIES`** / **`DB_INIT_RETRY_DELAY`** — повторы подключения к PostgreSQL при запуске процесса.
