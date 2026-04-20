"""
Tarea programada que se ejecuta cada 15 minutos para detectar reservas
que ocurrirán en las próximas 2 horas y enviarles el correo de recordatorio.
"""
import logging
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


def send_upcoming_reminders():
    """Envía correos de recordatorio a reservas dentro de 2 horas."""
    try:
        from apps.bookings.models import Booking
        from apps.bookings.emails import send_booking_reminder_email

        now = timezone.now()
        target_start = now + timedelta(hours=1, minutes=45)  # Ventana: entre 1h 45m
        target_end = now + timedelta(hours=2, minutes=15)    # y 2h 15m → ≈2 horas

        # Buscar reservas pendientes o confirmadas dentro de esa ventana y que NO tengan el reminder enviado
        from django.db.models import Q
        import datetime

        bookings_to_remind = Booking.objects.filter(
            status__in=['pending', 'confirmed'],
            reminder_sent=False,
            client_email__isnull=False
        ).exclude(client_email='')

        count = 0
        for booking in bookings_to_remind:
            # Combinar fecha y hora de la cita
            booking_dt = timezone.make_aware(
                datetime.datetime.combine(booking.date, booking.time),
                timezone.get_current_timezone()
            )
            if target_start <= booking_dt <= target_end:
                send_booking_reminder_email(booking)
                booking.reminder_sent = True
                booking.save(update_fields=['reminder_sent'])
                count += 1

        if count:
            logger.info(f"[Recordatorios] Enviados {count} correos de recordatorio.")
    except Exception as e:
        logger.error(f"[Recordatorios] Error en tarea de recordatorio: {e}")
