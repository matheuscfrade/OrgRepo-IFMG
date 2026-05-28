from .base import *

DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# Ensure required directories exist (important after fresh clone)
var_dir = BASE_DIR / 'var'
var_dir.mkdir(exist_ok=True)
(var_dir / 'media').mkdir(exist_ok=True)

# Use SQLite by default for development
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': var_dir / 'db.sqlite3',
    }
}

# For local PostgreSQL development, uncomment and configure:
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': os.getenv('DB_NAME', 'orgrepo'),
#         'USER': os.getenv('DB_USER', 'orgrepo'),
#         'PASSWORD': os.getenv('DB_PASSWORD', ''),
#         'HOST': os.getenv('DB_HOST', 'localhost'),
#         'PORT': os.getenv('DB_PORT', '5432'),
#     }
# }

# WhiteNoise not needed in development
MIDDLEWARE = [m for m in MIDDLEWARE if 'whitenoise' not in m.lower()]