# syntax=docker/dockerfile:1
# OrgRepo — production image (Django + Gunicorn)

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

WORKDIR /app

# System deps: build tools for psycopg if needed + client for health checks
# gosu: drop root → appuser after fixing volume ownership
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Python deps (production set)
COPY requirements/base.txt /app/requirements/base.txt
RUN pip install --upgrade pip \
    && pip install -r requirements/base.txt

# Application source
COPY . /app/

# Runtime dirs (media may be replaced by a Docker volume)
RUN mkdir -p /app/var/media /app/staticfiles \
    && chmod +x /app/scripts/docker-entrypoint.sh \
    && useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app

# Entrypoint starts as root to chown mounted volumes, then drops to appuser.
USER root

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:8000/" >/dev/null || exit 1

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
