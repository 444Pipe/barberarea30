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
# En producción real (con DATABASE_URL) la SECRET_KEY es obligatoria: nunca
# arrancar con la clave de desarrollo del repo, o se podrían falsificar los
# enlaces firmados (Signer), cookies de sesión y tokens.
SECRET_KEY = os.environ.get('SECRET_KEY') or (SECRET_KEY if IS_LOCAL else None)   # noqa: F405
if not SECRET_KEY:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        "La variable de entorno SECRET_KEY es obligatoria en producción."
    )
DEBUG = os.environ.get('DEBUG', 'True' if IS_LOCAL else 'False').lower() == 'true'

ALLOWED_HOSTS = _split_env(os.environ.get(
    'ALLOWED_HOSTS',
    'www.area30barberclub.com,area30barberclub.com,barberarea30-production.up.railway.app,localhost,127.0.0.1'
))

# ── Database (PostgreSQL via DATABASE_URL) ───────────────────────
_db_url = os.environ.get('DATABASE_URL', f"sqlite:///{BASE_DIR / 'bookings.db'}")
DATABASES = {
    'default': dj_database_url.config(
        default=_db_url,
        conn_max_age=0,
        conn_health_checks=True,
        ssl_require=True if 'postgresql' in _db_url or 'postgres' in _db_url else False,
    )
}

# ── Security ─────────────────────────────────────────────────────
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Estos deben ser False localmente (si no usas HTTPS)
SESSION_COOKIE_SECURE = not (IS_LOCAL or DEBUG)
CSRF_COOKIE_SECURE = not (IS_LOCAL or DEBUG)

_raw_csrf = os.environ.get(
    'CSRF_TRUSTED_ORIGINS',
    'https://www.area30barberclub.com,https://area30barberclub.com,https://barberarea30-production.up.railway.app,http://127.0.0.1:8000,http://localhost:8000'
)
CSRF_TRUSTED_ORIGINS = []
for origin in _split_env(_raw_csrf):
    if not origin.startswith('http://') and not origin.startswith('https://'):
        CSRF_TRUSTED_ORIGINS.append(f'https://{origin}')
    else:
        CSRF_TRUSTED_ORIGINS.append(origin)

# ── Static files (WhiteNoise) ───────────────────────────────────
# STATIC_ROOT y STATICFILES_STORAGE ya vienen de base.py
# Activar finders para servir además desde STATICFILES_DIRS
WHITENOISE_USE_FINDERS = True

# ── Cloudinary (media storage) ────────────────────────────────
if os.environ.get('CLOUDINARY_CLOUD_NAME'):
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': os.environ.get('CLOUDINARY_CLOUD_NAME'),
        'API_KEY': os.environ.get('CLOUDINARY_API_KEY', ''),
        'API_SECRET': os.environ.get('CLOUDINARY_API_SECRET', ''),
    }
STORAGES = {
    'default': {
        'BACKEND': 'cloudinary_storage.storage.MediaCloudinaryStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}
