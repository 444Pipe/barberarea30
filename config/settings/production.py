"""
Production settings — PostgreSQL via DATABASE_URL, DEBUG=False.
"""
import os

import dj_database_url

from .base import *  # noqa: F401,F403


def _split_env(value: str) -> list:
    """Convierte 'a, b, c' en ['a', 'b', 'c'] sin espacios vacíos."""
    return [v.strip() for v in value.split(',') if v.strip()]


# ── Core ─────────────────────────────────────────────────────────
IS_LOCAL = not os.environ.get('DATABASE_URL')
SECRET_KEY = os.environ.get('SECRET_KEY', SECRET_KEY)            # noqa: F405
DEBUG = os.environ.get('DEBUG', 'True' if IS_LOCAL else 'False').lower() == 'true'

ALLOWED_HOSTS = _split_env(os.environ.get(
    'ALLOWED_HOSTS',
    'barberarea30-production.up.railway.app,localhost,127.0.0.1'
))

# ── Database (PostgreSQL via DATABASE_URL) ───────────────────────
_db_url = os.environ.get('DATABASE_URL', f"sqlite:///{BASE_DIR / 'bookings.db'}")
DATABASES = {
    'default': dj_database_url.config(
        default=_db_url,
        conn_max_age=600,
        ssl_require=True if 'postgresql' in _db_url or 'postgres' in _db_url else False,
    )
}

# ── Security ─────────────────────────────────────────────────────
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True

# Estos deben ser False localmente (si no usas HTTPS)
SESSION_COOKIE_SECURE = not (IS_LOCAL or DEBUG)
CSRF_COOKIE_SECURE = not (IS_LOCAL or DEBUG)

CSRF_TRUSTED_ORIGINS = _split_env(os.environ.get(
    'CSRF_TRUSTED_ORIGINS',
    'https://barberarea30-production.up.railway.app,http://127.0.0.1:8000,http://localhost:8000'
))

# ── Static files (WhiteNoise) ───────────────────────────────────
# STATIC_ROOT y STATICFILES_STORAGE ya vienen de base.py
# Activar finders para servir además desde STATICFILES_DIRS
WHITENOISE_USE_FINDERS = True
