#!/bin/sh
set -e
cd /app
echo "docker-entrypoint: alembic upgrade head"
alembic upgrade head
exec python -m src.main
