# RUNBOOK — Telegram-бот приёмной комиссии

> **Стек:** Python · aiogram 3 · PostgreSQL · Redis · Docker Compose  
> **Кто ведёт:** Системный администратор или ответственный методист

### Структура каталогов `src/`

| Каталог | Назначение |
|---|---|
| `logic/abi/` | Абитуриент: главное меню, анкеты ДОД и специальности, напоминания ДОД, раздел «Обучение» |
| `logic/admin/` | Администратор: заявки, CSV, массовые рассылки, recovery задач после рестарта |
| `data/` | Модели БД (`models.py`), репозитории (`user_repository`), подключение |
| `monitoring/` | HTTP healthcheck, watchdog по БД, доставка ERROR в Telegram админу |
| `services/` | Сборка APScheduler с job store |
| Прочее | `config/`, `middlewares/`, `utils/` |

Аудит готовности к продакшену: `docs/PRODUCTION_READINESS_AUDIT.md`.

---

## 1. Быстрый деплой (с нуля)

### Требования к серверу

| Параметр | Минимум |
|---|---|
| OS | Ubuntu 22.04 LTS |
| CPU | 1 ядро |
| RAM | 1 ГБ |
| Диск | 20 ГБ |
| Docker | 24+ |
| Docker Compose | 2.20+ |

### Установка Docker (если не установлен)

```bash
curl -fsSL https://get.docker.com | bash
sudo usermod -aG docker $USER && newgrp docker
```

### Запуск бота

```bash
# 1. Скопировать проект на сервер
scp -r ./college_bot_fixed user@your-server:/opt/college-bot

# 2. Зайти на сервер
ssh user@your-server
cd /opt/college-bot

# 3. Создать .env из примера и заполнить значения
cp .env.example .env
nano .env          # Обязательно: BOT_TOKEN, ADMIN_ID, пароли БД

# 4. Запустить миграции и бота одной командой
docker compose up -d --build
docker compose exec bot alembic upgrade head

# 5. Проверить что всё работает
docker compose ps
docker compose logs bot --tail 20
```

### Обновление бота

```bash
cd /opt/college-bot
git pull                         # или scp новых файлов
docker compose down
docker compose up -d --build
docker compose exec bot alembic upgrade head
```

---

## 2. Настройка `.env` (описание ключей)

```dotenv
BOT_TOKEN=           # Токен от @BotFather (НИКОМУ не передавать)
ADMIN_ID=            # Ваш Telegram ID (узнать: написать @userinfobot)
DATABASE_URL=postgresql+asyncpg://user:pass@127.0.0.1:5432/college_db
POSTGRES_DB=college_db
POSTGRES_USER=user
POSTGRES_PASSWORD=   # Придумайте надёжный пароль (16+ символов)
REDIS_HOST=redis     # В Docker всегда redis
REDIS_PORT=6379
LOG_LEVEL=INFO
TZ=Europe/Moscow
```

**Миграции Alembic на Mac / Windows (venv):** в `.env` оставляйте хост **`db`** в `DATABASE_URL` (как для Docker). При запуске `alembic` **на хосте** адрес `db` автоматически подменяется на `127.0.0.1` (см. `alembic/env.py`). Порт Postgres должен быть доступен с машины (`127.0.0.1:5432`). Если в пароле есть символы вроде `!`, в строке URL используйте код **`%21`** вместо `!`.

**Контейнер бота и Postgres:** образ видит файл `/.dockerenv` и **не использует** поле `DATABASE_URL` для подключения к БД — строка собирается из **`POSTGRES_USER`**, **`POSTGRES_PASSWORD`**, **`POSTGRES_DB`** и хоста **`db`** (переменные те же, что у сервиса `db` в Compose). В `.env` можно держать `DATABASE_URL` с `127.0.0.1` только для локального Alembic на Mac. Обход: `DATABASE_USE_DOTENV_URL=1`.

**Проверка таблицы с ноутбука:** переменные `POSTGRES_*` из `.env` в вашем shell по умолчанию **не подставляются**. Используйте окружение уже внутри контейнера `db`:

```bash
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\\dt broadcast_recovery_jobs"'
```

(Двойной бэкслэш нужен из-за экранирования в `sh -c`.)

---

## 3. Смена дат Дней открытых дверей

1. Открыть файл `src/config/content.py`
2. Найти раздел `OPEN_DAY_DATES`
3. Заменить даты:

```python
OPEN_DAY_DATES: list[str] = [
    "15 сентября",
    "29 сентября",
    "13 октября",
    "27 октября",
]
```

4. Перезапустить бота:

```bash
docker compose restart bot
```

---

## 4. Ссылка на политику конфиденциальности

**Вариант A — загружать PDF-файл:**

Замените файл `policy.pdf` в корне проекта и перезапустите бота. Файл уже примонтирован в контейнер.

**Вариант B — ссылка на сайт:**

В `src/config/content.py` найдите `POLICY_URL = ""` и укажите URL:

```python
POLICY_URL = "https://ks54.ru/privacy-policy"
```

---

## 5. Бэкап базы данных

### Ручной бэкап

```bash
cd /opt/college-bot
docker compose exec db pg_dump \
  -U $POSTGRES_USER \
  -d $POSTGRES_DB \
  -F c \
  -f /tmp/backup.dump

docker compose cp db:/tmp/backup.dump ./backup_$(date +%Y%m%d).dump
```

### Автоматический бэкап (cron)

```bash
# Добавить в crontab (crontab -e):
0 3 * * * /opt/college-bot/backup_db.sh >> /var/log/bot-backup.log 2>&1
```

Скрипт `backup_db.sh` уже находится в корне проекта.

---

## 6. Восстановление из бэкапа

```bash
# ВНИМАНИЕ: пересоздаёт базу данных!
cd /opt/college-bot

# Остановить бота (база продолжает работать)
docker compose stop bot

# Скопировать файл бэкапа в контейнер
docker compose cp ./backup_20260502.dump db:/tmp/restore.dump

# Восстановить
docker compose exec db bash -c "
  dropdb -U \$POSTGRES_USER \$POSTGRES_DB --if-exists
  createdb -U \$POSTGRES_USER \$POSTGRES_DB
  pg_restore -U \$POSTGRES_USER -d \$POSTGRES_DB /tmp/restore.dump
"

# Запустить бота
docker compose start bot
docker compose logs bot --tail 30
```

---

## 7. Просмотр логов

```bash
# Логи бота в реальном времени
docker compose logs -f bot

# Логи последних 100 строк
docker compose logs bot --tail 100

# Лог-файл (хранится в томе)
docker compose exec bot cat /app/logs/bot.log
```

---

## 8. Решение проблем

### Бот не отвечает

```bash
docker compose ps            # Статус контейнеров (все должны быть Up)
docker compose logs bot --tail 50   # Искать ERROR / CRITICAL
docker compose restart bot   # Рестарт без потери данных
```

### Ошибка подключения к Redis

```bash
docker compose logs redis
docker compose exec redis redis-cli ping   # Должно вернуть PONG
```

### База данных не поднимается

```bash
docker compose logs db
docker compose exec db pg_isready -U $POSTGRES_USER
```

### Миграции Alembic

```bash
# Применить новые миграции
docker compose exec bot alembic upgrade head

# Откатить последнюю миграцию
docker compose exec bot alembic downgrade -1

# Посмотреть текущую версию
docker compose exec bot alembic current
```

**«relation … already exists»:** таблицы уже созданы старым способом (`create_all`), а версия Alembic не записана. Миграции `initial` и следующие сделаны идемпотентными (пропускают уже существующие объекты) — выполните снова `docker compose exec bot alembic upgrade head`.

Если ошибка повторяется, можно вручную пометить базу как уже имеющую начальную ревизию (данные не трогаются), затем докатить до head:

```bash
docker compose exec bot alembic stamp a29d64643ce3
docker compose exec bot alembic upgrade head
```

---

## 9. Доступ к админ-панели

1. Узнайте свой Telegram ID: напишите боту `@userinfobot`
2. Пропишите его в `.env`: `ADMIN_ID=123456789`
3. Перезапустите бота: `docker compose restart bot`
4. Напишите команду `/admin` в чате с ботом

**Возможности:**
- 📊 Статистика за 30 дней
- 📋 Просмотр и обработка новых заявок (CRM)
- 📥 Выгрузка в Excel (CSV с BOM)

---

## 10. Обновление контактов и текстов

Все тексты бота хранятся в одном файле: `src/config/content.py`.

Найдите нужный раздел (например, `SECTION_CONTACTS`) и замените текст.  
После изменения обязательно перезапустите бота:

```bash
docker compose restart bot
```

---

## 11. Контрольный список после деплоя

- [ ] `docker compose ps` — все три сервиса Up (db, redis, bot)  
- [ ] Бот отвечает на `/start`  
- [ ] `/admin` открывает панель (с правильным `ADMIN_ID`)  
- [ ] Форма ДОД: заявка сохраняется, admin получает уведомление  
- [ ] CSV-экспорт скачивается и открывается в Excel  
- [ ] Бэкап создаётся скриптом `backup_db.sh`  
- [ ] Сервер перезагружается → `restart: always` поднимает контейнеры автоматически
