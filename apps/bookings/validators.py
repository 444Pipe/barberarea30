"""Validaciones de disponibilidad para reservas.

Centraliza la verificación de bloqueos del local (BlockedDate),
inactividades del barbero (BarberUnavailability) y solapamientos
con otras reservas. Todas las rutas que crean o modifican un
Booking deben pasar por aquí.
"""
from datetime import datetime, timedelta, date as date_cls, time as time_cls

from apps.barbers.models import BarberUnavailability
from .models import Booking, BlockedDate


def _parse_date(value):
    if isinstance(value, date_cls) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.strptime(value, '%Y-%m-%d').date()
    raise ValueError(f'Fecha inválida: {value!r}')


def _parse_time(value):
    if isinstance(value, time_cls):
        return value
    if isinstance(value, str):
        for fmt in ('%H:%M:%S', '%H:%M'):
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                continue
    raise ValueError(f'Hora inválida: {value!r}')


def check_booking_conflict(
    *,
    barber,
    date,
    time,
    duration_minutes,
    exclude_booking_id=None,
    check_overlap=True,
):
    """Devuelve un string de error si la franja [date time, +duration) no se
    puede usar para reservar con `barber`. Devuelve None si está libre.

    Considera, en orden:
      1. BlockedDate (cierre total del local o ventana parcial de atención).
      2. BarberUnavailability del barbero (solape real, no solo hora de inicio).
      3. Reservas existentes del barbero que se cruzan (si check_overlap).
    """
    try:
        d = _parse_date(date)
        t = _parse_time(time)
    except ValueError as exc:
        return str(exc)

    dur = int(duration_minutes or 60)
    req_start = datetime.combine(d, t)
    req_end = req_start + timedelta(minutes=dur)

    # 1. BlockedDate global (local cerrado o ventana parcial)
    try:
        blocked = BlockedDate.objects.get(date=d)
    except BlockedDate.DoesNotExist:
        blocked = None

    if blocked is not None:
        if not blocked.start_time or not blocked.end_time:
            desc = f' ({blocked.description})' if blocked.description else ''
            return (
                f'El {d.strftime("%Y-%m-%d")} la barbería está cerrada{desc}. '
                f'Por favor elige otra fecha.'
            )
        if t < blocked.start_time or req_end.time() > blocked.end_time \
                or req_end.date() != req_start.date():
            return (
                f'El {d.strftime("%Y-%m-%d")} solo se atiende de '
                f'{blocked.start_time.strftime("%I:%M %p")} a '
                f'{blocked.end_time.strftime("%I:%M %p")}. '
                f'El horario elegido no cabe en esa franja.'
            )

    # 2. BarberUnavailability del barbero (solape real)
    if barber is not None:
        for u_start, u_end in BarberUnavailability.objects.filter(
            barber=barber, date=d
        ).values_list('start_time', 'end_time'):
            u_s = datetime.combine(d, u_start)
            u_e = datetime.combine(d, u_end)
            if u_s < req_end and u_e > req_start:
                name = getattr(barber, 'display_name', None) or 'El barbero'
                return (
                    f'{name} está bloqueado de '
                    f'{u_start.strftime("%I:%M %p")} a {u_end.strftime("%I:%M %p")} '
                    f'el {d.strftime("%Y-%m-%d")}. La reserva '
                    f'({t.strftime("%I:%M %p")}–{req_end.strftime("%I:%M %p")}) '
                    f'se cruza con ese bloqueo.'
                )

    # 3. Otras reservas del barbero (solape real)
    if check_overlap and barber is not None:
        qs = Booking.objects.filter(
            barber=barber, date=d, status__in=['pending', 'confirmed']
        )
        if exclude_booking_id is not None:
            qs = qs.exclude(pk=exclude_booking_id)
        for bk_time, bk_duration in qs.values_list('time', 'duration_minutes'):
            bk_start = datetime.combine(d, bk_time)
            bk_end = bk_start + timedelta(minutes=bk_duration or 60)
            if req_start < bk_end and req_end > bk_start:
                name = getattr(barber, 'display_name', None) or 'El barbero'
                return (
                    f'{name} ya tiene una cita activa que se cruza con las '
                    f'{t.strftime("%I:%M %p")} el {d.strftime("%Y-%m-%d")}. '
                    f'Por favor elige otro horario.'
                )

    return None
