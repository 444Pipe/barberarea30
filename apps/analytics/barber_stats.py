"""Estadísticas de UN barbero: cuánto vendió y cuánto ganó en un periodo.

Regla de atribución (oct-2026): una venta cuenta el día en que se hizo el
SERVICIO (`Booking.date`), no el día en que se registró el cobro
(`Sale.created_at`). Antes el dashboard del barbero usaba la fecha de cobro: el
7-oct Jesús atendió 3 servicios ($100.000) pero el tercero se cobró al día
siguiente y su tablero mostraba $60.000. Caja y Cierre sí deben usar la fecha
de cobro (es plata que entró ese día); esto es la vista del barbero.

"Vendido" = lo que pagó el cliente por el servicio (`final_price`, sin propina).
"Ganado"  = lo que le toca al barbero (`Commission.total_earnings`: comisión +
            propina). Las ventas rechazadas no cuentan; las pendientes de
            aprobación sí, pero se informan aparte.
"""
from collections import OrderedDict, defaultdict
from datetime import timedelta

from django.db.models import Q, Sum
from django.utils import timezone

WEEKDAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']


def sales_for_period(barber, start, end):
    """Ventas (no rechazadas) del barbero cuyo SERVICIO cae entre start y end."""
    from apps.cashflow.models import Sale

    return (
        Sale.objects.filter(barber=barber)
        .exclude(approval_status=Sale.STATUS_REJECTED)
        .filter(
            Q(booking__date__range=(start, end))
            | Q(booking__isnull=True, created_at__date__range=(start, end))
        )
        .select_related('booking', 'booking__service', 'service', 'commission')
    )


def _commission(sale):
    try:
        return sale.commission
    except Exception:  # venta vieja sin comisión
        return None


def _rows(barber, start, end):
    rows = []
    for s in sales_for_period(barber, start, end):
        com = _commission(s)
        created = timezone.localtime(s.created_at)
        bk = s.booking
        service = s.service or (bk.service if bk else None)
        rows.append({
            'id': s.id,
            'date': bk.date if bk else created.date(),
            'time': bk.time if bk else created.time(),
            'paid_on': created.date(),
            'client': (bk.client_name if bk else '') or 'Cliente',
            'phone': bk.client_phone if bk else '',
            'service': service.name if service else 'Servicio',
            'sold': int(s.final_price or 0),
            'tip': int(s.tip_amount or 0),
            'commission': int(com.commission_amount) if com else 0,
            'earned': int(com.total_earnings) if com else 0,
            'percentage': float(com.percentage) if com else None,
            'discount': int(s.discount_amount or 0),
            'pending': s.approval_status == 'pending',
        })
    return rows


def _totals(rows):
    sold = sum(r['sold'] for r in rows)
    clients = {(r['phone'] or r['client']).strip().lower() for r in rows}
    return {
        'sold': sold,
        'earned': sum(r['earned'] for r in rows),
        'commission': sum(r['commission'] for r in rows),
        'tips': sum(r['tip'] for r in rows),
        'services': len(rows),
        'avg_ticket': round(sold / len(rows)) if rows else 0,
        'clients': len(clients),
        'pending_sold': sum(r['sold'] for r in rows if r['pending']),
        'pending_count': sum(1 for r in rows if r['pending']),
        'paid_later': sum(1 for r in rows if r['paid_on'] != r['date']),
    }


def _delta(current, previous):
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def compute_barber_stats(barber, start, end, include_detail=True, prev_start=None, prev_end=None):
    """Todo lo que muestra el panel de estadísticas para [start, end].

    Se compara con [prev_start, prev_end]; si no se pasa, con el periodo
    inmediatamente anterior del mismo largo. El panel pasa el "mismo tramo" del
    periodo anterior (1-8 oct vs 1-8 sep) para que un mes a medias no parezca una caída.
    """
    from apps.cashflow.models import BarberAdvance, BarberPayment

    rows = _rows(barber, start, end)
    totals = _totals(rows)

    length = (end - start).days + 1
    if prev_start is None or prev_end is None or prev_end < prev_start:
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=length - 1)
    prev = _totals(_rows(barber, prev_start, prev_end))
    comparison = {
        'start': prev_start.isoformat(),
        'end': prev_end.isoformat(),
        'sold': prev['sold'],
        'earned': prev['earned'],
        'services': prev['services'],
        'delta': {
            'sold': _delta(totals['sold'], prev['sold']),
            'earned': _delta(totals['earned'], prev['earned']),
            'services': _delta(totals['services'], prev['services']),
            'avg_ticket': _delta(totals['avg_ticket'], prev['avg_ticket']),
            'tips': _delta(totals['tips'], prev['tips']),
        },
    }

    data = {
        'barber': {
            'id': barber.id,
            'name': barber.display_name,
            'commission_percentage': float(barber.commission_percentage),
        },
        'start': start.isoformat(),
        'end': end.isoformat(),
        'totals': totals,
        'previous': comparison,
    }
    if not include_detail:
        return data

    # Serie: por día hasta ~2 meses; por mes en rangos más largos.
    granularity = 'day' if length <= 62 else 'month'
    buckets = OrderedDict()
    cur = start
    while cur <= end:
        if granularity == 'day':
            key = cur.isoformat()
            label = f'{cur.day} {MONTHS[cur.month - 1]}'
            cur += timedelta(days=1)
        else:
            key = f'{cur.year}-{cur.month:02d}'
            label = f'{MONTHS[cur.month - 1]} {cur.year}'
            cur = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        buckets.setdefault(key, {'key': key, 'label': label, 'sold': 0, 'earned': 0, 'services': 0})
    for r in rows:
        key = r['date'].isoformat() if granularity == 'day' else f'{r["date"].year}-{r["date"].month:02d}'
        if key in buckets:
            b = buckets[key]
            b['sold'] += r['sold']
            b['earned'] += r['earned']
            b['services'] += 1

    by_service = defaultdict(lambda: {'count': 0, 'sold': 0, 'earned': 0})
    by_weekday = [{'day': name, 'services': 0, 'sold': 0} for name in WEEKDAYS]
    by_hour = defaultdict(int)
    for r in rows:
        svc = by_service[r['service']]
        svc['count'] += 1
        svc['sold'] += r['sold']
        svc['earned'] += r['earned']
        wd = by_weekday[r['date'].weekday()]
        wd['services'] += 1
        wd['sold'] += r['sold']
        by_hour[r['time'].hour] += 1

    top_services = sorted(
        ({'name': k, **v} for k, v in by_service.items()),
        key=lambda x: (-x['sold'], -x['count']),
    )
    best_day = max(by_weekday, key=lambda x: x['services']) if rows else None
    peak_hour = max(by_hour.items(), key=lambda kv: kv[1])[0] if by_hour else None

    advances = BarberAdvance.objects.filter(barber=barber, created_at__date__range=(start, end))
    payments = BarberPayment.objects.filter(barber=barber, created_at__date__range=(start, end))

    rows.sort(key=lambda r: (r['date'], r['time']), reverse=True)
    data.update({
        'granularity': granularity,
        'series': list(buckets.values()),
        'top_services': top_services[:8],
        'weekdays': by_weekday,
        'hours': [{'hour': h, 'services': by_hour[h]} for h in sorted(by_hour)],
        'best_day': best_day['day'] if best_day and best_day['services'] else None,
        'peak_hour': peak_hour,
        'advances': {
            'total': int(advances.aggregate(t=Sum('amount'))['t'] or 0),
            'count': advances.count(),
        },
        'payments': {
            'total': int(payments.aggregate(t=Sum('amount'))['t'] or 0),
            'count': payments.count(),
        },
        'sales': [{
            **{k: v for k, v in r.items() if k != 'phone'},
            'date': r['date'].isoformat(),
            'time': r['time'].strftime('%H:%M'),
            'paid_on': r['paid_on'].isoformat(),
        } for r in rows[:300]],
        'sales_total_count': len(rows),
    })
    return data
