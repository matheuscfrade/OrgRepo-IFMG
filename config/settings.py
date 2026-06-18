"""
Django settings router.

The actual settings are in the config/settings/ package.

To run with development settings:
    $env:DJANGO_SETTINGS_MODULE = "config.settings.development"
    python manage.py runserver

To run with production settings:
    $env:DJANGO_SETTINGS_MODULE = "config.settings.production"
    python manage.py runserver
"""

from config.settings.development import *  # noqa: F401,F403
