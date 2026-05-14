# Build image:
#   docker build -t college-bot:latest .
# Run container locally (reads .env from project root):
#   docker run --rm --env-file .env --name college-bot college-bot:latest

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies in a separate layer for better Docker cache reuse.
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for runtime security.
RUN useradd --create-home --shell /usr/sbin/nologin appuser

# Copy project sources after dependencies to preserve cache efficiency.
COPY src /app/src

# Alembic (миграции): при старте контейнера + вручную: docker compose exec bot alembic upgrade head
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

# Copy official privacy policy PDF (bundled in image + repo).
COPY policy.pdf /app/policy.pdf

# Optional runtime folders for file logs / local artifacts.
RUN chmod +x /app/docker-entrypoint.sh && mkdir -p /app/logs && chown -R appuser:appuser /app

USER appuser

# HTTP /healthz (см. HEALTHCHECK_PORT в .env; 0 = probe отключён, см. src/monitoring/docker_healthcheck.py)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -m src.monitoring.docker_healthcheck || exit 1

CMD ["/app/docker-entrypoint.sh"]
