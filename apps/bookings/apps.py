from django.apps import AppConfig


class BookingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.bookings'
    verbose_name = 'Reservas'

    def ready(self):
        """Inicia el scheduler de recordatorios automáticos cuando el servidor arranca."""
        import os
        # Evitar doble ejecución en modo desarrollo (reloader lanza 2 procesos)
        if os.environ.get('RUN_MAIN') != 'true' and os.environ.get('DJANGO_SETTINGS_MODULE'):
            return
        
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
