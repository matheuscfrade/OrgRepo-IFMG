"""
Django settings router.

By default uses development settings.
Override with DJANGO_SETTINGS_MODULE=config.settings.production
"""

import os

# Default to development settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

from .development import *  # noqa: F401,F403
