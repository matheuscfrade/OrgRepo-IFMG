#!/bin/sh
# OrgRepo Docker entrypoint (production)
# - fix media/static volume ownership (as root), then drop to appuser
# - wait for Postgres
# - migrate + collectstatic
# - optional one-shot bootstrap (RUN_BOOTSTRAP=full|foundation)
# - start gunicorn

set -e

echo "[entrypoint] Starting OrgRepo..."

# ---------------------------------------------------------------------------
# Privileged bootstrap: writable volumes for uid 1000 (appuser)
# ---------------------------------------------------------------------------
if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/var/media /app/staticfiles
  chown -R appuser:appuser /app/var /app/staticfiles 2>/dev/null || true
  # Re-exec as appuser for the rest of the process (security)
  exec gosu appuser "$0" "$@"
fi

# ---------------------------------------------------------------------------
# Build DATABASE_URL with URL-encoded credentials when only POSTGRES_* are set
# ---------------------------------------------------------------------------
if [ -z "${DATABASE_URL:-}" ] && [ -n "${POSTGRES_PASSWORD:-}" ]; then
  export DATABASE_URL="$(
    python - <<'PY'
import os
from urllib.parse import quote

user = os.environ.get("POSTGRES_USER", "orgrepo")
password = os.environ.get("POSTGRES_PASSWORD", "")
host = os.environ.get("POSTGRES_HOST", "db")
port = os.environ.get("POSTGRES_PORT", "5432")
name = os.environ.get("POSTGRES_DB") or os.environ.get("POSTGRES_DATABASE") or "orgrepo"
print(
    f"postgres://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{name}"
)
PY
  )"
  echo "[entrypoint] DATABASE_URL built from POSTGRES_* (password URL-encoded)."
fi

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

url = os.environ.get("DATABASE_URL")
if not url:
    sys.exit(0)

cfg = dj_database_url.parse(url)
try:
    import psycopg
except ImportError:
    print("[entrypoint] psycopg not available; cannot wait for DB", flush=True)
    sys.exit(1)

host = cfg.get("HOST") or "localhost"
port = int(cfg.get("PORT") or 5432)
user = cfg.get("USER") or ""
password = cfg.get("PASSWORD") or ""
dbname = cfg.get("NAME") or ""

deadline = time.time() + int(os.environ.get("DB_WAIT_SECONDS", "90"))
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
# Failures here abort the container (set -e) so TI does not see a false-healthy stack.
BOOTSTRAP="${RUN_BOOTSTRAP:-}"
if [ "$BOOTSTRAP" = "full" ]; then
  echo "[entrypoint] RUN_BOOTSTRAP=full — loading full snapshot + normative models..."
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
