"""
Production settings for OrgRepo (Docker / institutional server).

Required environment variables (see .env.example and docs/deploy-docker.md):
  - SECRET_KEY or DJANGO_SECRET_KEY
  - DATABASE_URL
  - ALLOWED_HOSTS or DJANGO_ALLOWED_HOSTS
"""

from __future__ import annotations

import os
from pathlib import Path

from .base import *  # noqa: F401,F403

DEBUG = False


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Secrets & hosts
# ---------------------------------------------------------------------------
SECRET_KEY = (
    os.getenv("SECRET_KEY")
    or os.getenv("DJANGO_SECRET_KEY")
    or SECRET_KEY  # from base (insecure fallback)
)

if (
    not SECRET_KEY
    or SECRET_KEY.startswith("django-insecure-")
    or SECRET_KEY in {"change-this-in-production", "your-super-secret-key-here-generate-with-django-utils"}
):
    if not _env_bool("ALLOW_INSECURE_SECRET_KEY", False):
        raise RuntimeError(
            "Production SECRET_KEY is missing or insecure. "
            "Set SECRET_KEY (or DJANGO_SECRET_KEY) in the environment. "
            "For local Docker smoke tests only, set ALLOW_INSECURE_SECRET_KEY=1."
        )

ALLOWED_HOSTS = _env_list("ALLOWED_HOSTS") or _env_list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise RuntimeError(
        "Production ALLOWED_HOSTS is empty. "
        "Set ALLOWED_HOSTS (or DJANGO_ALLOWED_HOSTS) to your domain/IP list."
    )

CSRF_TRUSTED_ORIGINS = _env_list("CSRF_TRUSTED_ORIGINS")

# ---------------------------------------------------------------------------
# Database (PostgreSQL)
# ---------------------------------------------------------------------------
import dj_database_url  # noqa: E402

_database_url = os.getenv("DATABASE_URL")
if not _database_url:
    raise RuntimeError(
        "DATABASE_URL is required in production. "
        "Example: postgres://user:pass@db:5432/orgrepo"
    )

DATABASES = {
    "default": dj_database_url.config(
        default=_database_url,
        conn_max_age=int(os.getenv("DB_CONN_MAX_AGE", "600")),
        ssl_require=_env_bool("DB_SSL_REQUIRE", False),
    )
}

# ---------------------------------------------------------------------------
# Security (env-tunable for reverse-proxy TLS termination)
# ---------------------------------------------------------------------------
SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", True)
CSRF_COOKIE_SECURE = _env_bool("CSRF_COOKIE_SECURE", True)
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# Trust X-Forwarded-Proto from institutional reverse proxy
if _env_bool("USE_X_FORWARDED_PROTO", True):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if _env_bool("SECURE_HSTS", SECURE_SSL_REDIRECT):
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = _env_bool("SECURE_HSTS_PRELOAD", False)

# ---------------------------------------------------------------------------
# Static (WhiteNoise) & media
# ---------------------------------------------------------------------------
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Ensure media directory exists (Docker volume may mount empty)
Path(MEDIA_ROOT).mkdir(parents=True, exist_ok=True)

# Serve uploaded PDFs from Django when not using an external media proxy.
# Default True for first institutional go-live with local volume.
SERVE_MEDIA = _env_bool("SERVE_MEDIA", True)

# ---------------------------------------------------------------------------
# Logging (stdout — container-friendly)
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
