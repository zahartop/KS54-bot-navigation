#!/usr/bin/env bash
# Подготовка .env к prod: права доступа и проверка DEBUG.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${1:-.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Файл не найден: $ENV_FILE (укажите путь первым аргументом при необходимости)" >&2
  exit 1
fi

chmod 600 "$ENV_FILE"
echo "Права на $ENV_FILE установлены: 600"

if grep -E '^[[:space:]]*DEBUG[[:space:]]*=[[:space:]]*(1|true|True|yes|YES)[[:space:]]*(#.*)?$' "$ENV_FILE" 2>/dev/null; then
  echo "ОШИБКА: в $ENV_FILE DEBUG включён. В production задайте DEBUG=0 или удалите строку." >&2
  exit 1
fi

echo "Проверка DEBUG: ок (нет явного включения)."
