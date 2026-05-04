#!/usr/bin/env bash
# =============================================================================
# deploy.sh — одноразовая настройка Ubuntu VPS и запуск college-bot
#
# Использование:
#   1. Скопировать на сервер:
#        scp deploy.sh user@YOUR_VPS_IP:/home/user/
#   2. Запустить от имени обычного пользователя (не root):
#        chmod +x deploy.sh && ./deploy.sh
#
# Скрипт идемпотентен: при повторном запуске не сломает работающий бот.
# =============================================================================
set -euo pipefail

# --------------------------------------------------------------------------- #
#  КОНФИГ — поменяй под свои значения
# --------------------------------------------------------------------------- #
PROJECT_DIR="${HOME}/college-bot"
BOT_USER="${USER}"

# --------------------------------------------------------------------------- #
#  ЦВЕТА для читаемого вывода
# --------------------------------------------------------------------------- #
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
section() { echo -e "\n${YELLOW}━━━ $* ━━━${NC}"; }

# --------------------------------------------------------------------------- #
#  Не запускать от root
# --------------------------------------------------------------------------- #
[[ "${EUID}" -eq 0 ]] && error "Запускай от обычного пользователя, НЕ root. (sudo доступен при необходимости)"

section "1 / 6 · Обновление системы"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
sudo apt-get install -y -qq curl git ufw fail2ban
info "Система обновлена."

# --------------------------------------------------------------------------- #
section "2 / 6 · Файрволл (UFW)"
# --------------------------------------------------------------------------- #
if ! sudo ufw status | grep -q "Status: active"; then
    sudo ufw default deny incoming
    sudo ufw default allow outgoing
    sudo ufw allow OpenSSH
    sudo ufw --force enable
    info "UFW включён: разрешён только SSH."
else
    info "UFW уже активен, пропускаем."
fi

# --------------------------------------------------------------------------- #
section "3 / 6 · Установка Docker"
# --------------------------------------------------------------------------- #
if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker --version)
    info "Docker уже установлен: ${DOCKER_VER}"
else
    info "Устанавливаем Docker..."
    curl -fsSL https://get.docker.com | sudo sh
    info "Docker установлен."
fi

# Добавить текущего пользователя в группу docker (без sudo)
if ! groups "${BOT_USER}" | grep -q docker; then
    sudo usermod -aG docker "${BOT_USER}"
    warn "Пользователь добавлен в группу docker."
    warn "Для применения группы выйди и войди снова (или выполни: newgrp docker)."
fi

# --------------------------------------------------------------------------- #
section "4 / 6 · Настройка директории проекта"
# --------------------------------------------------------------------------- #
mkdir -p "${PROJECT_DIR}"
mkdir -p "${PROJECT_DIR}/scripts"
mkdir -p "${HOME}/backups"
mkdir -p "${HOME}/logs"
info "Директории созданы: ${PROJECT_DIR}, ~/backups, ~/logs"

# Копируем файлы проекта, если они ещё не там
# (при деплое с локальной машины — файлы уже должны быть скопированы через scp/rsync)
REQUIRED_FILES=("docker-compose.yml" "Dockerfile" "requirements.txt")
MISSING=0
for f in "${REQUIRED_FILES[@]}"; do
    [[ ! -f "${PROJECT_DIR}/${f}" ]] && warn "Файл не найден: ${PROJECT_DIR}/${f}" && MISSING=$((MISSING+1))
done

if [[ ${MISSING} -gt 0 ]]; then
    warn "Скопируй файлы проекта на сервер:"
    warn "  rsync -avz --exclude='venv' --exclude='__pycache__' \\"
    warn "    /путь/к/college_bot_fixed/ ${BOT_USER}@VPS_IP:${PROJECT_DIR}/"
    error "Прерываю. Повтори запуск после копирования файлов."
fi

# --------------------------------------------------------------------------- #
section "5 / 6 · Проверка / создание .env"
# --------------------------------------------------------------------------- #
if [[ -f "${PROJECT_DIR}/.env" ]]; then
    info ".env уже существует, пропускаем."
else
    if [[ -f "${PROJECT_DIR}/.env.example" ]]; then
        cp "${PROJECT_DIR}/.env.example" "${PROJECT_DIR}/.env"
        chmod 600 "${PROJECT_DIR}/.env"
        warn ".env создан из .env.example — ОБЯЗАТЕЛЬНО заполни его реальными значениями!"
        warn "Открой: nano ${PROJECT_DIR}/.env"
        warn "Заполни: BOT_TOKEN, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD"
        echo ""
        read -rp "Нажми Enter после того как заполнишь .env..." _
    else
        warn ".env.example не найден. Создаём .env вручную..."
        cat > "${PROJECT_DIR}/.env" << 'ENVEOF'
BOT_TOKEN=ЗАМЕНИ_НА_РЕАЛЬНЫЙ_ТОКЕН
POSTGRES_DB=college_db
POSTGRES_USER=college_user
POSTGRES_PASSWORD=ЗАМЕНИ_НА_СИЛЬНЫЙ_ПАРОЛЬ
TZ=Europe/Moscow
LOG_LEVEL=INFO
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800
DB_CONNECT_TIMEOUT=10
DB_INIT_MAX_RETRIES=10
DB_INIT_RETRY_DELAY=3
DB_WRITE_MAX_RETRIES=3
DB_WRITE_RETRY_DELAY=1
DB_WRITE_TIMEOUT=10
ENVEOF
        chmod 600 "${PROJECT_DIR}/.env"
        warn ".env создан. Открой и заполни: nano ${PROJECT_DIR}/.env"
        read -rp "Нажми Enter после заполнения .env..." _
    fi
fi

# Проверяем, что BOT_TOKEN не заглушка
BOT_TOKEN_VAL=$(grep "^BOT_TOKEN=" "${PROJECT_DIR}/.env" | cut -d= -f2-)
if [[ -z "${BOT_TOKEN_VAL}" || "${BOT_TOKEN_VAL}" == *"ЗАМЕНИ"* || "${BOT_TOKEN_VAL}" == *"replace"* ]]; then
    error ".env содержит заглушку BOT_TOKEN. Заполни реальный токен и повтори запуск."
fi

# --------------------------------------------------------------------------- #
section "6 / 6 · Запуск бота"
# --------------------------------------------------------------------------- #
cd "${PROJECT_DIR}"

# Копируем скрипты (backup, restore) в ~/scripts если они есть в проекте
if [[ -f "${PROJECT_DIR}/scripts/backup_db.sh" ]]; then
    cp "${PROJECT_DIR}/scripts/backup_db.sh" "${HOME}/scripts/"
    chmod +x "${HOME}/scripts/backup_db.sh"
    info "backup_db.sh установлен в ~/scripts/"
fi

# Собираем и запускаем
info "Собираем образ и запускаем контейнеры..."
docker compose pull 2>/dev/null || true
docker compose build --no-cache
docker compose up -d

# Ждём старта (до 60 секунд)
info "Ожидаем готовности бота (до 60 сек)..."
for i in $(seq 1 12); do
    sleep 5
    STATUS=$(docker compose ps --format json 2>/dev/null | python3 -c "
import sys, json
lines = [json.loads(l) for l in sys.stdin if l.strip()]
for s in lines:
    name = s.get('Name','')
    state = s.get('State','')
    if 'bot-app' in name:
        print(state)
" 2>/dev/null || echo "unknown")
    if [[ "${STATUS}" == "running" ]]; then
        info "Бот запущен! (попытка ${i}/12)"
        break
    fi
    warn "Статус: ${STATUS} (попытка ${i}/12)..."
done

echo ""
info "═══════════════════════════════════════════"
info "  Деплой завершён успешно!"
info "  Полезные команды:"
info "    docker compose logs -f bot        # логи бота"
info "    docker compose ps                 # статус"
info "    docker compose restart bot        # перезапуск"
info "    ~/scripts/backup_db.sh            # бэкап БД"
info "═══════════════════════════════════════════"

# --------------------------------------------------------------------------- #
#  CRON для автоматического бэкапа (раз в сутки в 02:00)
# --------------------------------------------------------------------------- #
if [[ -f "${HOME}/scripts/backup_db.sh" ]]; then
    CRON_LINE="0 2 * * * set -a; source ${PROJECT_DIR}/.env; set +a; ${HOME}/scripts/backup_db.sh >> ${HOME}/logs/backup.log 2>&1"
    if crontab -l 2>/dev/null | grep -qF "backup_db.sh"; then
        info "Cron для бэкапа уже настроен."
    else
        (crontab -l 2>/dev/null; echo "${CRON_LINE}") | crontab -
        info "Cron для бэкапа добавлен: каждый день в 02:00."
    fi
fi
