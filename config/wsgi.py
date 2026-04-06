"""WSGI config for Área 30 Barber Club."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE',
                      os.environ.get('DJANGO_SETTINGS_MODULE',
                                     'config.settings.production'))

# FORZAR MIGRACIONES EN TIEMPO DE EJECUCIÓN (RUNTIME)
# Esto soluciona el bug crítico de Railway donde DATABASE_URL no está disponible 
# durante la fase de release (build), causando que las migraciones vayan a SQLite.
if os.environ.get('DATABASE_URL'):
    print("⏳ Aplicando migraciones directamente en Postgres durante arranque WSGI...")
    os.system('python manage.py migrate --noinput')
    os.system('python seed.py')
    print("✅ Migraciones de arranque finalizaron.")

application = get_wsgi_application()
