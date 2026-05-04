#!/usr/bin/env bash
# =============================================================================
# backup_db.sh — ежедневный бэкап PostgreSQL из Docker-контейнера
#
# Запуск вручную:
#   source ~/college-bot/.env && ~/scripts/backup_db.sh
#
# Через cron (раз в сутки в 02:00, добавляется автоматически deploy.sh):
#   0 2 * * * set -a; source ~/college-bot/.env; set +a; ~/scripts/backup_db.sh >> ~/logs/backup.log 2>&1
# =============================================================================
set -euo pipefail

# --------------------------------------------------------------------------- #
#  КОНФИГ (переменные берутся из .env через cron или source)
# --------------------------------------------------------------------------- #
CONTAINER="${BACKUP_CONTAINER:-college-bot-db}"
DB_NAME="${POSTGRES_DB:-college_db}"
DB_USER="${POSTGRES_USER:-college_user}"
BACKUP_DIR="${BACKUP_DIR:-${HOME}/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
DUMP_FILE="${BACKUP_DIR}/college_db_${TIMESTAMP}.dump"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

# --------------------------------------------------------------------------- #
#  Проверки перед запуском
# --------------------------------------------------------------------------- #
mkdir -p "${BACKUP_DIR}"

if ! docker inspect "${CONTAINER}" &>/dev/null; then
    echo "${LOG_PREFIX} [ERROR] Контейнер '${CONTAINER}' не найден. Бэкап прерван." >&2
    exit 1
fi

CONTAINER_STATUS=$(docker inspect --format='{{.State.Status}}' "${CONTAINER}")
if [[ "${CONTAINER_STATUS}" != "running" ]]; then
    echo "${LOG_PREFIX} [ERROR] Контейнер '${CONTAINER}' не запущен (статус: ${CONTAINER_STATUS}). Бэкап прерван." >&2
    exit 1
fi

# --------------------------------------------------------------------------- #
#  Создание дампа
# --------------------------------------------------------------------------- #
echo "${LOG_PREFIX} [INFO] Запуск бэкапа → ${DUMP_FILE}"

docker exec "${CONTAINER}" \
    pg_dump \
    --username="${DB_USER}" \
    --format=custom \
    --compress=9 \
    --no-privileges \
    --no-owner \
    "${DB_NAME}" \
    > "${DUMP_FILE}"

# --------------------------------------------------------------------------- #
#  Валидация: файл должен быть непустым и иметь корректный заголовок pg_dump
# --------------------------------------------------------------------------- #
if [[ ! -s "${DUMP_FILE}" ]]; then
    echo "${LOG_PREFIX} [ERROR] Дамп пустой! Удаляем артефакт." >&2
    rm -f "${DUMP_FILE}"
    exit 1
fi

# pg_dump custom-format начинается с байт "PGDMP"
MAGIC=$(dd if="${DUMP_FILE}" bs=5 count=1 2>/dev/null)
if [[ "${MAGIC}" != "PGDMP" ]]; then
    echo "${LOG_PREFIX} [ERROR] Дамп имеет неверный заголовок — возможно, pg_dump вернул ошибку." >&2
    echo "${LOG_PREFIX} [ERROR] Первые байты: ${MAGIC}" >&2
    rm -f "${DUMP_FILE}"
    exit 1
fi

DUMP_SIZE=$(du -sh "${DUMP_FILE}" | cut -f1)
echo "${LOG_PREFIX} [OK]   Дамп создан: $(basename "${DUMP_FILE}") (${DUMP_SIZE})"

# --------------------------------------------------------------------------- #
#  Ротация старых бэкапов
# --------------------------------------------------------------------------- #
DELETED=0
while IFS= read -r old_file; do
    rm -f "${old_file}"
    echo "${LOG_PREFIX} [INFO] Удалён старый дамп: $(basename "${old_file}")"
    DELETED=$((DELETED + 1))
done < <(find "${BACKUP_DIR}" -maxdepth 1 -name "college_db_*.dump" -mtime "+${RETENTION_DAYS}")

[[ ${DELETED} -eq 0 ]] && echo "${LOG_PREFIX} [INFO] Ротация: нет файлов старше ${RETENTION_DAYS} дней."

# --------------------------------------------------------------------------- #
#  Итоговая статистика
# --------------------------------------------------------------------------- #
TOTAL=$(find "${BACKUP_DIR}" -maxdepth 1 -name "college_db_*.dump" | wc -l | tr -d ' ')
TOTAL_SIZE=$(du -sh "${BACKUP_DIR}" 2>/dev/null | cut -f1)
echo "${LOG_PREFIX} [INFO] Итого дампов: ${TOTAL} (суммарно ${TOTAL_SIZE}). Бэкап завершён."
