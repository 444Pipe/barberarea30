from django.apps import AppConfig


class BookingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.bookings'
    verbose_name = 'Reservas'

    def ready(self):
        """Inicia el scheduler de recordatorios automáticos cuando el servidor arranca."""
        import os
        import sys

        argv = sys.argv
        prog = os.path.basename(argv[0]) if argv else ''

        # Bajo runserver, solo el proceso recargado (RUN_MAIN='true') arranca el
        # scheduler; el padre del reloader no debe hacerlo.
        if 'runserver' in argv:
            if os.environ.get('RUN_MAIN') != 'true':
                return
        # Comandos de gestión (migrate, shell, seed_services…) y el seed de
        # arranque (python seed.py) no sirven la app: nunca arrancan el scheduler.
        elif prog in ('manage.py', 'django-admin', 'seed.py') or 'pytest' in prog:
            return
        # Cualquier otro caso (gunicorn/uwsgi sirviendo la app) sí lo arranca.

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.interval import IntervalTrigger
            from django.conf import settings

            if getattr(settings, 'TESTING', False):
                return  # No correr scheduler en tests

            from .scheduler import send_upcoming_reminders

            scheduler = BackgroundScheduler(timezone='America/Bogota')
            scheduler.add_job(
                send_upcoming_reminders,
                trigger=IntervalTrigger(minutes=15),
                id='booking_reminders',
                name='Envío de recordatorios de citas',
                replace_existing=True,
            )
            scheduler.start()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"No se pudo iniciar el scheduler: {e}")
