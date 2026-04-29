from django.apps import AppConfig


class RoiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.roi'
    verbose_name = 'ROI & Ganancias'

    def ready(self):
        """Arranca el scheduler de consolidación mensual al iniciar Django."""
        import sys
        # No arrancar en comandos de gestión como makemigrations, shell, etc.
        if 'runserver' in sys.argv or 'gunicorn' in sys.argv[0:1]:
            from apps.roi.scheduler import start_roi_scheduler
            start_roi_scheduler()
