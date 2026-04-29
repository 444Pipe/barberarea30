"""
ROI Scheduler — Tarea programada para consolidar el snapshot ROI
el primer día de cada mes a las 00:05 (hora Colombia).

Se integra con APScheduler (ya incluido en requirements.txt).
Para activarlo, importa start_roi_scheduler() desde el AppConfig.ready()
o desde el manage.py de arranque.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.utils import timezone

logger = logging.getLogger(__name__)

_scheduler = None


def _consolidate_previous_month():
    """Tarea que corre el día 1 de cada mes a las 00:05."""
    from django.contrib.auth.models import User
    from apps.roi.services import generate_monthly_snapshot

    now = timezone.localtime(timezone.now())
    # El "mes anterior" al día 1 actual
    if now.month == 1:
        year, month = now.year - 1, 12
    else:
        year, month = now.year, now.month - 1

    try:
        # Usamos el primer superadmin disponible como "sistema"
        system_user = User.objects.filter(
            profile__role='superadmin', is_active=True
        ).first()

        snapshot = generate_monthly_snapshot(year, month, user=system_user)
        logger.info(
            f'[ROI Scheduler] Snapshot generado: {month}/{year} — '
            f'Neto: ${snapshot.net_income:,.0f} COP'
        )
    except ValueError as e:
        logger.warning(f'[ROI Scheduler] Snapshot omitido: {e}')
    except Exception as e:
        logger.error(f'[ROI Scheduler] Error generando snapshot: {e}', exc_info=True)


def start_roi_scheduler():
    """
    Arranca el scheduler. Llamar una sola vez al inicio de la aplicación.
    Si ya está corriendo, no hace nada.
    """
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone='America/Bogota')

    # Ejecutar el día 1 de cada mes a las 00:05
    _scheduler.add_job(
        _consolidate_previous_month,
        trigger=CronTrigger(day=1, hour=0, minute=5),
        id='roi_monthly_consolidation',
        name='ROI — Consolidar Mes Anterior',
        replace_existing=True,
        misfire_grace_time=3600,  # 1 hora de tolerancia si el server estuvo caído
    )

    _scheduler.start()
    logger.info('[ROI Scheduler] Iniciado — consolidación mensual activa (día 1, 00:05 COT).')
