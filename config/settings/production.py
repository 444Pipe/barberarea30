"""
Production settings — PostgreSQL via DATABASE_URL, DEBUG=False.
"""
import os

import dj_database_url

from .base import *  # noqa: F401,F403

DEBUG = False
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

# Permite usar ALLOWED_HOSTS o, si no existe, ALLOWED_HOST (como fallback)
ALLOWED_HOSTS = os.environ.get(
    'ALLOWED_HOSTS',
    os.environ.get('ALLOWED_HOST', '*')
).split(',')

DATABASES = {
    'default': dj_database_url.config(
        default=os.environ.get('DATABASE_URL'),
        conn_max_age=600,
        ssl_require=True,
    )
}

# Security
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

CSRF_TRUSTED_ORIGINS = os.environ.get(
    'CSRF_TRUSTED_ORIGINS',
    'https://barberarea30-production.up.railway.app'
).split(',')

# WhiteNoise: en Railway preferimos usar los finders de Django
# para servir directamente desde la carpeta "static/".
WHITENOISE_USE_FINDERS = True
