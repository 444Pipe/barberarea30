"""
Alertas operativas de caja (jobs del scheduler + endpoint del panel):

1. Servicios sin cerrar: citas de HOY que ya pasaron hace ~3 horas y siguen
   sin checkout (status pending/confirmed — las completadas siempre tienen
   Sale vía process_checkout). Corre cada 15 min; envía UN correo digest.
2. Recordatorio de cierre de caja: a las 9 pm, si aún no hay DailyClose de
   hoy y quedan movimientos pendientes.

Destinatarios: superadmins activos con email + el usuario operativo `frank`.

Dedup multi-worker (cada proceso gunicorn corre su propio scheduler):
- servicios sin cerrar → claim atómico sobre Booking.close_alert_sent
  (mismo patrón de apps/bookings/scheduler.py).
- recordatorio de cierre → CashflowAlertLog con UniqueConstraint (tipo, día).

Los correos van con fail_silently=True (igual que los recordatorios de citas):
si SMTP falla, la alerta de ese día se pierde — trade-off aceptado.
"""
import datetime
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

UNCLOSED_GRACE_HOURS = 3


def get_alert_recipients():
    """Emails de los superadmins activos + frank, sin duplicados ni vacíos."""
    from django.contrib.auth.models import User

    users = User.objects.filter(
        is_active=True, profile__role__in=('superadmin', 'operational_admin')
    ).exclude(email='')
    emails = []
    for u in users:
        if u.email and u.email not in emails:
            emails.append(u.email)
    return emails


def get_unclosed_bookings(now=None):
    """Citas de HOY sin checkout cuya hora de fin pasó hace más de ~3 horas."""
    from apps.bookings.models import Booking

    now = now or timezone.now()
    tz = timezone.get_current_timezone()
    today = timezone.localtime(now).date()
    yesterday = today - timedelta(days=1)

    # Incluir también las citas de AYER: una cita de la noche (p.ej. 21:30) cuya
    # ventana de gracia (fin + 3h) cae pasada la medianoche solo se detecta ya
    # entrado el día siguiente; sin ayer quedaría en una ventana muerta.
    candidates = Booking.objects.filter(
        date__in=[today, yesterday], status__in=['pending', 'confirmed']
    ).select_related('barber', 'service')

    unclosed = []
    for booking in candidates:
        start = timezone.make_aware(
            datetime.datetime.combine(booking.date, booking.time), tz
        )
        end = start + timedelta(minutes=booking.duration_minutes or 60)
        if end + timedelta(hours=UNCLOSED_GRACE_HOURS) < now:
            unclosed.append(booking)
    return unclosed


def send_unclosed_services_alert():
    """Job cada 15 min: digest de servicios sin cerrar (email + AuditLog)."""
    try:
        from apps.bookings.models import Booking
        from apps.bookings.emails import _send_html_email
        from apps.analytics.models import log_audit
        from django.conf import settings

        unclosed = get_unclosed_bookings()
        if not unclosed:
            return

        # Reclamar atómicamente los que aún no dispararon alerta: si otro
        # worker ya los marcó, update() devuelve 0 y no se re-envía.
        fresh_ids = [b.pk for b in unclosed if not b.close_alert_sent]
        claimed = 0
        if fresh_ids:
            claimed = Booking.objects.filter(
                pk__in=fresh_ids, close_alert_sent=False
            ).update(close_alert_sent=True)
        if not claimed:
            return

        # Digest con TODOS los pendientes (no solo los recién reclamados),
        # para que el correo pinte la foto completa del día.
        site_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
        context = {
            'bookings': unclosed,
            'count': len(unclosed),
            'site_url': site_url,
            'panel_url': f'{site_url}/admin-panel/bookings/',
        }
        recipients = get_alert_recipients()
        for email in recipients:
            _send_html_email(
                f'⚠ {len(unclosed)} servicio(s) del día sin cerrar - Área 30',
                'emails/unclosed_services_alert.html',
                context,
                email,
            )

        log_audit(
            user=None,
            action='update',
            obj=None,
            changes={},
            extra_data={'msg': f"ALERTA: {len(unclosed)} servicio(s) del día llevan +{UNCLOSED_GRACE_HOURS}h sin cerrar (checkout pendiente)"},
        )
        logger.info(f"[Alertas] Servicios sin cerrar: {len(unclosed)} pendientes, {claimed} nuevos, {len(recipients)} correos.")
    except Exception as e:
        logger.error(f"[Alertas] Error en alerta de servicios sin cerrar: {e}")


def send_daily_close_reminder():
    """Job cron 21:00: recuerda hacer el cierre de caja si hay pendientes."""
    try:
        from django.db import IntegrityError
        from django.db.models import Sum
        from apps.cashflow.models import DailyClose, Sale, InventorySale, Expense, CashflowAlertLog
        from apps.bookings.emails import _send_html_email
        from apps.analytics.models import log_audit
        from django.conf import settings

        today = timezone.localtime().date()
        if DailyClose.objects.filter(date=today).exists():
            return

        pending_sales = Sale.objects.filter(
            approval_status=Sale.STATUS_APPROVED, included_in_daily_close__isnull=True
        )
        pending_inventory = InventorySale.objects.filter(included_in_daily_close__isnull=True)
        pending_expenses = Expense.objects.filter(included_in_daily_close__isnull=True)
        pending_approvals = Sale.objects.filter(
            approval_status=Sale.STATUS_PENDING, included_in_daily_close__isnull=True
        ).count()

        # El cierre requiere ventas o inventario (daily_close_view corta si no
        # hay ninguno). Un egreso suelto NO habilita el cierre —se absorbe en un
        # cierre futuro con ventas—, así que no debe disparar el recordatorio.
        if not (pending_sales.exists() or pending_inventory.exists()):
            return  # nada cerrable hoy

        # Candado multi-worker: solo el primer proceso inserta y envía.
        try:
            CashflowAlertLog.objects.create(alert_type='close_reminder', date=today)
        except IntegrityError:
            return

        total_sales = pending_sales.aggregate(t=Sum('final_price'))['t'] or 0
        total_inventory = pending_inventory.aggregate(t=Sum('total_price'))['t'] or 0
        total_expenses = pending_expenses.aggregate(t=Sum('amount'))['t'] or 0

        site_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
        context = {
            'date': today,
            'sales_count': pending_sales.count() + pending_inventory.count(),
            'total_sales': total_sales,
            'total_inventory': total_inventory,
            'total_expenses': total_expenses,
            'pending_approvals': pending_approvals,
            'site_url': site_url,
            'panel_url': f'{site_url}/admin-panel/cashflow/',
        }
        recipients = get_alert_recipients()
        for email in recipients:
            _send_html_email(
                '🕘 Recuerda hacer el cierre de caja de hoy - Área 30',
                'emails/daily_close_reminder.html',
                context,
                email,
            )

        log_audit(
            user=None,
            action='update',
            obj=None,
            changes={},
            extra_data={'msg': f"ALERTA: cierre de caja del {today} pendiente a las 9 pm ({context['sales_count']} venta(s) sin cerrar)"},
        )
        logger.info(f"[Alertas] Recordatorio de cierre enviado a {len(recipients)} destinatarios.")
    except Exception as e:
        logger.error(f"[Alertas] Error en recordatorio de cierre: {e}")
