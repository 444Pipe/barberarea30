"""
Build-time settings — solo para collectstatic durante el build de la imagen Docker.
Sin dependencias de variables de entorno / Docker secrets.
"""
from .base import *  # noqa: F401, F403

DEBUG = False
SECRET_KEY = 'build-time-placeholder-not-used-in-production'
ALLOWED_HOSTS = ['*']

# Base de datos en memoria — solo se necesita para que Django no falle al importar
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Email dummy — no se envían correos durante el build
EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
EMAIL_HOST = 'localhost'
EMAIL_PORT = 25
EMAIL_USE_TLS = False
EMAIL_HOST_USER = ''
EMAIL_HOST_PASSWORD = ''
DEFAULT_FROM_EMAIL = 'build@example.com'
EMAIL_ADMIN = ''
SITE_URL = 'https://www.area30barberclub.com'

# Cloudinary desactivado — usar filesystem durante build
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# Deshabilitar Cloudinary storage en build
CLOUDINARY_STORAGE = {}
