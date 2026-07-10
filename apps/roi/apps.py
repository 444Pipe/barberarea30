from django.apps import AppConfig


class RoiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.roi'
    verbose_name = 'ROI & Ganancias'

    def ready(self):
        """Arranca el scheduler de consolidación mensual al iniciar Django."""
        import os
        import sys

        argv = sys.argv
        prog = os.path.basename(argv[0]) if argv else ''

        # Bajo runserver, solo el proceso recargado (RUN_MAIN='true').
        if 'runserver' in argv:
            if os.environ.get('RUN_MAIN') != 'true':
                return
        # Comandos de gestión y el seed de arranque no sirven la app.
        elif prog in ('manage.py', 'django-admin', 'seed.py') or 'pytest' in prog:
            return
        # gunicorn/uwsgi sirviendo la app: arranca la consolidación.

        from apps.roi.scheduler import start_roi_scheduler
        start_roi_scheduler()
