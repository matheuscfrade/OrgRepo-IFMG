#!/bin/sh
# OrgRepo Docker entrypoint (production)
# - wait for Postgres
# - migrate + collectstatic
# - optional one-shot bootstrap (RUN_BOOTSTRAP=full|foundation)
# - start gunicorn

set -e

echo "[entrypoint] Starting OrgRepo..."

# ---------------------------------------------------------------------------
# Wait for database
# ---------------------------------------------------------------------------
if [ -n "${DATABASE_URL:-}" ]; then
  echo "[entrypoint] Waiting for database..."
  python - <<'PY'
import os
import sys
import time

import dj_database_url
from django.db import connection
from django.conf import settings

# Minimal settings bootstrap for DB check without full Django app load if needed
url = os.environ.get("DATABASE_URL")
if not url:
    sys.exit(0)

cfg = dj_database_url.parse(url)
# Use raw psycopg connection for health wait (no Django setup required)
try:
    import psycopg
except ImportError:
    print("[entrypoint] psycopg not available; skipping DB wait", flush=True)
    sys.exit(0)

host = cfg.get("HOST") or "localhost"
port = int(cfg.get("PORT") or 5432)
user = cfg.get("USER") or ""
password = cfg.get("PASSWORD") or ""
dbname = cfg.get("NAME") or ""

deadline = time.time() + int(os.environ.get("DB_WAIT_SECONDS", "60"))
last_err = None
while time.time() < deadline:
    try:
        with psycopg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname,
            connect_timeout=3,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        print("[entrypoint] Database is ready.", flush=True)
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        last_err = exc
        time.sleep(2)

print(f"[entrypoint] Database not ready after timeout: {last_err}", flush=True)
sys.exit(1)
PY
fi

# ---------------------------------------------------------------------------
# Django bootstrap
# ---------------------------------------------------------------------------
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.production}"

echo "[entrypoint] Running migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Collecting static files..."
python manage.py collectstatic --noinput

# One-shot data bootstrap (never leave RUN_BOOTSTRAP=full permanently)
#   foundation → load_consup44_modelos
#   full       → load_full_data + load_consup44_modelos + sync_cargo_quotas
BOOTSTRAP="${RUN_BOOTSTRAP:-}"
if [ "$BOOTSTRAP" = "full" ]; then
  echo "[entrypoint] RUN_BOOTSTRAP=full — loading full snapshot + normative models..."
  echo "[entrypoint] NOTE: data/full_data.json must already reflect finalized organograms (dump after edits in dev)."
  python manage.py load_full_data
  python manage.py load_consup44_modelos
  python manage.py sync_cargo_quotas
  echo "[entrypoint] Bootstrap complete. Unset RUN_BOOTSTRAP for subsequent restarts."
elif [ "$BOOTSTRAP" = "foundation" ]; then
  echo "[entrypoint] RUN_BOOTSTRAP=foundation — loading CONSUP 44 models..."
  python manage.py load_consup44_modelos
  echo "[entrypoint] Bootstrap complete. Unset RUN_BOOTSTRAP for subsequent restarts."
else
  echo "[entrypoint] No data bootstrap (RUN_BOOTSTRAP unset)."
fi

# ---------------------------------------------------------------------------
# Gunicorn
# ---------------------------------------------------------------------------
WORKERS="${GUNICORN_WORKERS:-3}"
TIMEOUT="${GUNICORN_TIMEOUT:-120}"
BIND="${GUNICORN_BIND:-0.0.0.0:8000}"

echo "[entrypoint] Starting gunicorn (workers=${WORKERS}, bind=${BIND})..."
exec gunicorn \
  --bind "$BIND" \
  --workers "$WORKERS" \
  --timeout "$TIMEOUT" \
  --access-logfile - \
  --error-logfile - \
  config.wsgi:application
