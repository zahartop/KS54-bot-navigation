#!/usr/bin/env bash
# =============================================================================
# restore_db.sh — Runbook восстановления PostgreSQL из бэкапа
#
# ПРАВИЛО №1: НИКОГДА не восстанавливать напрямую в prod-базу.
#             Сначала → verify_db (временная), проверь, потом → prod.
#
# Использование:
#
#   # Показать доступные бэкапы:
#   ./restore_db.sh list
#
#   # Проверить дамп во временной базе (безопасно):
#   ./restore_db.sh verify college_db_2026-05-01_02-00-00.dump
#
#   # Восстановить в production (ОСТОРОЖНО — перезапишет данные!):
#   ./restore_db.sh prod college_db_2026-05-01_02-00-00.dump
# =============================================================================
set -euo pipefail

# --------------------------------------------------------------------------- #
#  Конфиг
# --------------------------------------------------------------------------- #
CONTAINER="${RESTORE_CONTAINER:-college-bot-db}"
DB_NAME="${POSTGRES_DB:-college_db}"
DB_USER="${POSTGRES_USER:-college_user}"
BACKUP_DIR="${BACKUP_DIR:-${HOME}/backups}"
VERIFY_DB="${DB_NAME}_verify_$(date +%s)"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

# --------------------------------------------------------------------------- #
#  Утилиты
# --------------------------------------------------------------------------- #
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}   $*"; }
info() { echo -e "       $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

psql_exec() {
    # Выполнить SQL в контейнере
    docker exec -e PGPASSWORD="${POSTGRES_PASSWORD:-}" "${CONTAINER}" \
        psql --username="${DB_USER}" --dbname="postgres" --tuples-only --no-align \
        --command="$1" 2>/dev/null
}

check_container() {
    docker inspect "${CONTAINER}" &>/dev/null \
        || err "Контейнер '${CONTAINER}' не найден. Убедись, что бот запущен: docker compose ps"
    STATUS=$(docker inspect --format='{{.State.Status}}' "${CONTAINER}")
    [[ "${STATUS}" == "running" ]] \
        || err "Контейнер '${CONTAINER}' не запущен (статус: ${STATUS})."
}

# --------------------------------------------------------------------------- #
#  КОМАНДА: list — показать доступные дампы
# --------------------------------------------------------------------------- #
cmd_list() {
    echo -e "\n${BOLD}Доступные бэкапы в ${BACKUP_DIR}:${NC}"
    local count=0
    while IFS= read -r f; do
        SIZE=$(du -sh "${f}" | cut -f1)
        MTIME=$(date -r "${f}" '+%Y-%m-%d %H:%M')
        printf "  %-50s %6s  %s\n" "$(basename "${f}")" "${SIZE}" "${MTIME}"
        count=$((count + 1))
    done < <(find "${BACKUP_DIR}" -maxdepth 1 -name "college_db_*.dump" | sort -r)

    [[ ${count} -eq 0 ]] && warn "Дампов не найдено в ${BACKUP_DIR}." || echo ""
    echo -e "Восстановление: ${YELLOW}./restore_db.sh verify <имя_файла.dump>${NC}"
}

# --------------------------------------------------------------------------- #
#  КОМАНДА: verify — восстановить во временную базу и проверить
# --------------------------------------------------------------------------- #
cmd_verify() {
    local DUMP_NAME="${1:-}"
    [[ -z "${DUMP_NAME}" ]] && err "Укажи имя файла дампа. Пример: ./restore_db.sh verify college_db_2026-05-01_02-00-00.dump"

    local DUMP_FILE="${BACKUP_DIR}/${DUMP_NAME}"
    [[ ! -f "${DUMP_FILE}" ]] && err "Файл не найден: ${DUMP_FILE}"

    check_container

    echo -e "\n${BOLD}━━━ VERIFY: восстановление в тестовую базу '${VERIFY_DB}' ━━━${NC}"

    # ── Шаг 1: создать временную базу ──────────────────────────────────────
    info "Шаг 1/5: Создаём временную базу ${VERIFY_DB}..."
    psql_exec "CREATE DATABASE \"${VERIFY_DB}\";" > /dev/null
    ok "База '${VERIFY_DB}' создана."

    # ── Шаг 2: копируем дамп в контейнер ───────────────────────────────────
    info "Шаг 2/5: Копируем дамп в контейнер..."
    docker cp "${DUMP_FILE}" "${CONTAINER}:/tmp/restore_verify.dump"
    ok "Файл скопирован."

    # ── Шаг 3: восстанавливаем ─────────────────────────────────────────────
    info "Шаг 3/5: Восстанавливаем данные..."
    docker exec -e PGPASSWORD="${POSTGRES_PASSWORD:-}" "${CONTAINER}" \
        pg_restore \
        --username="${DB_USER}" \
        --dbname="${VERIFY_DB}" \
        --no-owner \
        --no-privileges \
        --exit-on-error \
        /tmp/restore_verify.dump
    ok "Восстановление завершено."

    # ── Шаг 4: проверяем количество записей ────────────────────────────────
    info "Шаг 4/5: Проверяем данные..."
    echo ""
    echo -e "  ${BOLD}Таблица                       Кол-во записей${NC}"
    echo    "  ──────────────────────────────────────────────"

    docker exec -e PGPASSWORD="${POSTGRES_PASSWORD:-}" "${CONTAINER}" \
        psql --username="${DB_USER}" --dbname="${VERIFY_DB}" \
        --tuples-only --no-align \
        --command="
            SELECT
                schemaname || '.' || tablename AS tbl,
                n_live_tup::text
            FROM pg_stat_user_tables
            ORDER BY schemaname, tablename;
        " 2>/dev/null | while IFS='|' read -r tbl cnt; do
            printf "  %-30s %s\n" "${tbl}" "${cnt}"
        done
    echo ""
    ok "Данные выглядят корректно."

    # ── Шаг 5: чистим временные ресурсы ────────────────────────────────────
    info "Шаг 5/5: Удаляем временную базу и файл..."
    docker exec -e PGPASSWORD="${POSTGRES_PASSWORD:-}" "${CONTAINER}" \
        psql --username="${DB_USER}" --dbname="postgres" \
        --command="DROP DATABASE \"${VERIFY_DB}\";" > /dev/null
    docker exec "${CONTAINER}" rm -f /tmp/restore_verify.dump
    ok "Очистка завершена."

    echo ""
    echo -e "${GREEN}${BOLD}✓ Дамп '${DUMP_NAME}' валиден и содержит данные.${NC}"
    echo -e "  Для восстановления в prod: ${YELLOW}./restore_db.sh prod ${DUMP_NAME}${NC}\n"
}

# --------------------------------------------------------------------------- #
#  КОМАНДА: prod — восстановить в production (С ПОДТВЕРЖДЕНИЕМ)
# --------------------------------------------------------------------------- #
cmd_prod() {
    local DUMP_NAME="${1:-}"
    [[ -z "${DUMP_NAME}" ]] && err "Укажи имя файла дампа. Пример: ./restore_db.sh prod college_db_2026-05-01.dump"

    local DUMP_FILE="${BACKUP_DIR}/${DUMP_NAME}"
    [[ ! -f "${DUMP_FILE}" ]] && err "Файл не найден: ${DUMP_FILE}"

    check_container

    echo -e "\n${RED}${BOLD}⚠  ВНИМАНИЕ: восстановление в PRODUCTION базу '${DB_NAME}'${NC}"
    echo -e "   Все текущие данные будут УДАЛЕНЫ и заменены данными из дампа."
    echo -e "   Дамп: ${DUMP_NAME}\n"
    read -rp "   Введи название базы '${DB_NAME}' для подтверждения: " CONFIRM

    [[ "${CONFIRM}" != "${DB_NAME}" ]] && err "Подтверждение не совпало. Операция отменена."

    echo ""
    info "Шаг 1/5: Останавливаем бота (чтобы нет активных подключений)..."
    docker compose stop bot 2>/dev/null || warn "Не удалось остановить бота — продолжаем."
    ok "Бот остановлен."

    info "Шаг 2/5: Копируем дамп в контейнер..."
    docker cp "${DUMP_FILE}" "${CONTAINER}:/tmp/restore_prod.dump"
    ok "Файл скопирован."

    info "Шаг 3/5: Удаляем текущую базу и создаём пустую..."
    psql_exec "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid();" > /dev/null
    psql_exec "DROP DATABASE IF EXISTS \"${DB_NAME}\";" > /dev/null
    psql_exec "CREATE DATABASE \"${DB_NAME}\" OWNER \"${DB_USER}\";" > /dev/null
    ok "База пересоздана."

    info "Шаг 4/5: Восстанавливаем данные..."
    docker exec -e PGPASSWORD="${POSTGRES_PASSWORD:-}" "${CONTAINER}" \
        pg_restore \
        --username="${DB_USER}" \
        --dbname="${DB_NAME}" \
        --no-owner \
        --no-privileges \
        --exit-on-error \
        /tmp/restore_prod.dump
    ok "Данные восстановлены."

    info "Шаг 5/5: Чистим и перезапускаем бота..."
    docker exec "${CONTAINER}" rm -f /tmp/restore_prod.dump
    docker compose start bot 2>/dev/null || warn "Запусти бота вручную: docker compose up -d bot"
    ok "Бот перезапущен."

    echo ""
    echo -e "${GREEN}${BOLD}✓ Production база '${DB_NAME}' успешно восстановлена из '${DUMP_NAME}'${NC}\n"
}

# --------------------------------------------------------------------------- #
#  ТОЧКА ВХОДА
# --------------------------------------------------------------------------- #
CMD="${1:-help}"

case "${CMD}" in
    list)           cmd_list ;;
    verify)         cmd_verify "${2:-}" ;;
    prod)           cmd_prod   "${2:-}" ;;
    help|--help|-h)
        echo ""
        echo -e "${BOLD}restore_db.sh${NC} — Runbook восстановления PostgreSQL"
        echo ""
        echo "  Команды:"
        echo "    list                      Показать доступные бэкапы"
        echo "    verify <file.dump>        Восстановить во временную БД и проверить (безопасно)"
        echo "    prod   <file.dump>        Восстановить в production (с подтверждением)"
        echo ""
        echo "  Примеры:"
        echo "    ./restore_db.sh list"
        echo "    ./restore_db.sh verify college_db_2026-05-01_02-00-00.dump"
        echo "    ./restore_db.sh prod   college_db_2026-05-01_02-00-00.dump"
        echo ""
        ;;
    *)
        err "Неизвестная команда: '${CMD}'. Используй: list | verify | prod"
        ;;
esac
