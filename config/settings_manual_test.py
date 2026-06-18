from .settings.development import *  # noqa: F401,F403

IS_MANUAL_TEST = True

VAR_DIR = BASE_DIR / 'var'
MANUAL_TEST_DIR = VAR_DIR / 'manual_test'
MANUAL_TEST_MEDIA_ROOT = MANUAL_TEST_DIR / 'media'

MANUAL_TEST_DIR.mkdir(parents=True, exist_ok=True)
MANUAL_TEST_MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': MANUAL_TEST_DIR / 'db.sqlite3',
    }
}

MEDIA_ROOT = MANUAL_TEST_MEDIA_ROOT
