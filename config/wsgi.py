"""WSGI config for Área 30 Barber Club."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE',
                      os.environ.get('DJANGO_SETTINGS_MODULE',
                                     'config.settings.production'))

application = get_wsgi_application()

# ── Auto-migrate en arranque (útil para Railway/Producción) ──
try:
    from django.core.management import call_command
    call_command('migrate', interactive=False)
except Exception as e:
    print(f"WSGI Auto-migrate warning: {e}")
