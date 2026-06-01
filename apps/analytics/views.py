"""Analytics API — stats computed from booking data."""
from collections import defaultdict
from django.utils import timezone as tz

from django.db.models import Sum, Count, Avg

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.users.permissions import IsAdminOrAbove, IsBarberOrAbove
from apps.bookings.models import Booking
from apps.barbers.models import Barber


@api_view(['GET'])
@permission_classes([IsBarberOrAbove])
def revenue_stats_view(request):
    """
    GET /api/admin/stats/revenue/?period=month&barber=1
    Ingresos por período, filtrable por barbero.
    """
    profile = getattr(request.user, 'profile', None)
    queryset = Booking.objects.filter(status='completed')

    # Barbers can only see their own stats
    if profile and profile.is_barber and not profile.is_admin:
        barber = getattr(request.user, 'barber_profile', None)
        queryset = queryset.filter(barber=barber) if barber else queryset.none()

    barber_id = request.query_params.get('barber')
    if barber_id:
        queryset = queryset.filter(barber_id=barber_id)

    # Group by month
    monthly = defaultdict(int)
    for b in queryset:
        key = b.date.strftime('%Y-%m')
        monthly[key] += int(b.price)

    sorted_keys = sorted(monthly.keys())
    result = [{'month': k, 'revenue': monthly[k]} for k in sorted_keys]

    # Summary
    total = sum(monthly.values())
    return Response({
        'total_revenue': total,
        'months': result,
    })


@api_view(['GET'])
@permission_classes([IsBarberOrAbove])
def services_stats_view(request):
    """GET /api/admin/stats/services/ — servicios más vendidos."""
    profile = getattr(request.user, 'profile', None)
    queryset = Booking.objects.filter(status='completed')

    if profile and profile.is_barber and not profile.is_admin:
        barber = getattr(request.user, 'barber_profile', None)
        queryset = queryset.filter(barber=barber) if barber else queryset.none()

    services = (
        queryset.values('service__name')
        .annotate(count=Count('id'), revenue=Sum('price'))
        .order_by('-count')[:10]
    )

    return Response(list(services))


@api_view(['GET'])
@permission_classes([IsAdminOrAbove])
def barber_performance_view(request):
    """GET /api/admin/stats/barbers/performance/ — rendimiento por barbero."""
    barbers = Barber.objects.all()
    result = []

    for barber in barbers:
        completed = Booking.objects.filter(barber=barber, status='completed')
        stats = completed.aggregate(
            total_revenue=Sum('price'),
            total_bookings=Count('id'),
            avg_ticket=Avg('price'),
        )
        unique_clients = completed.values('client_phone').distinct().count()

        result.append({
            'id': barber.id,
            'name': barber.display_name,
            'color': barber.color_tag,
            'avatar': barber.avatar.url if barber.avatar else None,
            'total_bookings': stats['total_bookings'] or 0,
            'total_revenue': stats['total_revenue'] or 0,
            'avg_ticket': round(stats['avg_ticket'] or 0),
            'unique_clients': unique_clients,
        })

    result.sort(key=lambda x: x['total_revenue'], reverse=True)
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAdminOrAbove])
def heatmap_view(request):
    """GET /api/admin/stats/heatmap/ — horas pico (día × hora)."""
    bookings = Booking.objects.exclude(status='cancelled')
    heatmap = defaultdict(lambda: defaultdict(int))

    for b in bookings:
        day = b.date.strftime('%A').lower()
        hour = b.time.hour
        heatmap[day][hour] += 1

    days = ['monday', 'tuesday', 'wednesday', 'thursday',
            'friday', 'saturday', 'sunday']
    result = []
    for day in days:
        for hour in range(7, 22):
            result.append({
                'day': day,
                'hour': hour,
                'count': heatmap[day][hour],
            })

    return Response(result)


@api_view(['GET'])
@permission_classes([IsBarberOrAbove])
def dashboard_stats_view(request):
    """GET /api/admin/stats/dashboard/ — KPIs para el dashboard."""
    from datetime import date, timedelta, datetime
    from django.utils import timezone

    profile = getattr(request.user, 'profile', None)
    
    date_str = request.query_params.get('date')
    if date_str:
        try:
            today = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            today = date.today()
    else:
        today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    base = Booking.objects.all()

    # Barbers see only their own
    if profile and profile.is_barber and not profile.is_admin:
        barber = getattr(request.user, 'barber_profile', None)
        base = base.filter(barber=barber) if barber else base.none()

    completed = base.filter(status='completed')

    # Revenue: contar solo ventas APROBADAS para que coincida con Caja.
    # Antes se sumaba Booking.price de las reservas 'completed', incluyendo
    # las que tenían Sale pendiente de aprobación (Frank aún no la confirmaba),
    # generando discrepancias con la vista de cashflow.
    from apps.cashflow.models import Sale
    sales_qs = Sale.objects.filter(approval_status=Sale.STATUS_APPROVED)
    if profile and profile.is_barber and not profile.is_admin:
        barber = getattr(request.user, 'barber_profile', None)
        sales_qs = sales_qs.filter(barber=barber) if barber else sales_qs.none()

    day_revenue = sales_qs.filter(created_at__date=today).aggregate(r=Sum('final_price'))['r'] or 0
    week_revenue = sales_qs.filter(created_at__date__gte=week_start).aggregate(r=Sum('final_price'))['r'] or 0
    month_revenue = sales_qs.filter(created_at__date__gte=month_start).aggregate(r=Sum('final_price'))['r'] or 0

    # Pending bookings
    pending_count = base.filter(status='pending').count()

    # Today's bookings for Kanban
    today_bookings = (
        base.filter(date=today)
        .select_related('barber', 'service')
        .order_by('time')
    )

    kanban = defaultdict(list)
    for b in today_bookings:
        barber_name = b.barber.display_name if b.barber else 'Sin asignar'
        kanban[barber_name].append({
            'id': b.id,
            'time': b.time.strftime('%I:%M %p'),
            'client': b.client_name,
            'service': b.service.name if b.service else '',
            'status': b.status,
            'price': int(b.price),
        })

    # Cancel rate (this month)
    month_total = base.filter(date__gte=month_start).count()
    month_cancelled = base.filter(date__gte=month_start, status='cancelled').count()
    cancel_rate = round((month_cancelled / month_total * 100) if month_total else 0, 1)

    # Top barber this month
    top_barber = (
        completed.filter(date__gte=month_start)
        .values('barber__display_name')
        .annotate(count=Count('id'))
        .order_by('-count')
        .first()
    )

    return Response({
        'revenue': {
            'day': day_revenue,
            'week': week_revenue,
            'month': month_revenue,
        },
        'pending_count': pending_count,
        'cancel_rate': cancel_rate,
        'top_barber': top_barber['barber__display_name'] if top_barber else '-',
        'today_kanban': dict(kanban),
    })


from apps.analytics.models import AuditLog

@api_view(['GET'])
@permission_classes([IsAdminOrAbove])
def notifications_view(request):
    """GET /api/admin/notifications/ — ultimos movimientos para superadmins."""
    profile = getattr(request.user, 'profile', None)
    if not profile or not profile.is_superadmin:
        return Response({'error': 'Sin acceso a auditoría'}, status=403)

    logs = AuditLog.objects.all().order_by('-created_at')[:20]
    
    result = []
    for log in logs:
        if log.user:
            user_name = log.user.get_full_name() or log.user.username
        else:
            user_name = 'Sistema'
        msg = log.extra_data.get('msg', f"Realizó una acción: {log.get_action_display()}")

        result.append({
            'id': log.id,
            'user': user_name,
            'action': log.action,
            'message': msg,
            'time': tz.localtime(log.created_at).strftime('%d %b, %I:%M %p')
        })

    return Response(result)


@api_view(['GET'])
@permission_classes([IsAdminOrAbove])
def audit_log_api_view(request):
    """
    GET /api/admin/audit/logs/
    Devuelve el log completo de auditoría en JSON.
    Restringido a superadmin y admin (batman). Frank (operational_admin) y barberos no tienen acceso.
    """
    profile = getattr(request.user, 'profile', None)
    # Solo superadmin y admin (no operational_admin, no barber)
    if not profile or profile.role not in ('superadmin', 'admin'):
        return Response({'error': 'Acceso restringido. Solo administradores principales.'}, status=403)

    logs = AuditLog.objects.select_related('user').order_by('-created_at')[:500]

    result = []
    for log in logs:
        if log.user:
            user_name = log.user.get_full_name() or log.user.username
        else:
            user_name = 'Sistema'
        msg = log.extra_data.get('msg', f'Realizó: {log.get_action_display()}')
        result.append({
            'id':          log.id,
            'datetime':    tz.localtime(log.created_at).strftime('%d/%m/%Y  %I:%M:%S %p'),
            'user':        user_name,
            'action':      log.action,
            'model_name':  log.model_name,
            'object_id':   log.object_id,
            'object_repr': log.object_repr,
            'changes':     log.changes,
            'ip':          log.ip_address,
            'msg':         msg,
        })

    return Response(result)


@api_view(['GET'])
@permission_classes([IsAdminOrAbove])
def monthly_report_view(request):
    """
    GET /api/admin/reports/monthly/?year=2026&month=4
    Reporte financiero mensual consolidado — solo superadmins.
    """
    from apps.users.permissions import IsSuperAdmin
    from apps.cashflow.models import Sale, Commission, Expense, DailyClose
    from apps.barbers.models import Barber
    from django.db.models import Sum, Count
    from django.utils import timezone
    import datetime

    profile = getattr(request.user, 'profile', None)
    if not profile or not profile.is_superadmin:
        return Response({'error': 'Acceso restringido a SuperAdmins.'}, status=403)

    now = timezone.localtime(timezone.now())
    year = int(request.query_params.get('year', now.year))
    month = int(request.query_params.get('month', now.month))

    # Date range
    first_day = datetime.date(year, month, 1)
    if month == 12:
        last_day = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        last_day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    # Sales in range — solo APROBADAS (las pendientes pueden ser rechazadas)
    sales = Sale.objects.filter(
        created_at__date__gte=first_day,
        created_at__date__lte=last_day,
        approval_status=Sale.STATUS_APPROVED,
    )
    totals = sales.aggregate(
        total_sales=Sum('final_price'),
        total_tips=Sum('tip_amount'),
        total_discounts=Sum('discount_amount'),
    )

    # Commissions: Frank ya está contabilizado como Expense diaria
    # ("Pago Diario: Franko"); si sumamos también su Commission.commission_amount
    # acá lo estaríamos contando dos veces en el net_income.
    commissions = Commission.objects.filter(sale__in=sales)
    non_frank_commissions = commissions.exclude(barber__display_name__icontains='frank')
    total_commissions = non_frank_commissions.aggregate(t=Sum('commission_amount'))['t'] or 0
    # Para mostrar la "torta total" sí sumamos todas
    total_commissions_all = commissions.aggregate(t=Sum('commission_amount'))['t'] or 0

    # Expenses in range
    expenses = Expense.objects.filter(date__gte=first_day, date__lte=last_day)
    total_expenses = expenses.aggregate(t=Sum('amount'))['t'] or 0

    # Las propinas que Frank cobra dentro de su "Pago Diario" son pass-through
    # (cliente→barbero), no son gasto de la empresa. Las restamos del total
    # antes de calcular el net para no inflar el costo.
    frank_commissions_qs = commissions.filter(barber__display_name__icontains='frank')
    frank_tips = frank_commissions_qs.aggregate(t=Sum('tip_amount'))['t'] or 0
    frank_comm_only = frank_commissions_qs.aggregate(t=Sum('commission_amount'))['t'] or 0
    # Pago diario que se le hace a Frank vía Expense (comisión + propinas).
    frank_payout = float(frank_comm_only) + float(frank_tips)
    expenses_for_net = float(total_expenses) - float(frank_tips)
    # Egresos NO relacionados con el pago a Frank (más útil para el KPI).
    expenses_non_frank = float(total_expenses) - frank_payout

    # Net income
    total_income = float(totals['total_sales'] or 0)
    net_income = total_income - float(total_commissions) - expenses_for_net

    # Daily closes for the month
    daily_closes = DailyClose.objects.filter(date__gte=first_day, date__lte=last_day).order_by('date')
    closes_data = [{
        'date': dc.date.strftime('%d/%m/%Y'),
        'net_income': float(dc.net_income),
        'total_sales': float(dc.total_sales),
        'total_commissions': float(dc.total_commissions),
        'total_expenses': float(dc.total_expenses),
        'is_verified': dc.is_verified,
        'closed_by': ((dc.closed_by.get_full_name() or dc.closed_by.username) if dc.closed_by else 'N/A'),
    } for dc in daily_closes]

    # Barber ranking for the month
    barber_ranking = []
    for barber in Barber.objects.all():
        barber_sales = sales.filter(barber=barber)
        barber_commissions = commissions.filter(barber=barber)
        b_income = float(barber_sales.aggregate(t=Sum('final_price'))['t'] or 0)
        b_commission = float(barber_commissions.aggregate(t=Sum('total_earnings'))['t'] or 0)
        b_cuts = barber_sales.count()
        if b_cuts > 0:
            barber_ranking.append({
                'name': barber.display_name,
                'color': barber.color_tag,
                'cuts': b_cuts,
                'generated': b_income,
                'earned': b_commission,
            })
    barber_ranking.sort(key=lambda x: x['generated'], reverse=True)

    return Response({
        'period': f"{first_day.strftime('%B %Y')}",
        'year': year,
        'month': month,
        'kpis': {
            'total_sales': total_income,
            'total_tips': float(totals['total_tips'] or 0),
            'total_discounts': float(totals['total_discounts'] or 0),
            # Comisiones del EQUIPO (no incluye a Frank — su pago diario
            # ya está dentro de total_expenses como "Pago Diario: Franko").
            # Antes este valor incluía a Frank y, sumado mentalmente con
            # total_expenses, double-conteaba su comisión.
            'total_commissions': float(total_commissions),
            'frank_payout': frank_payout,
            'total_expenses': float(total_expenses),
            'total_expenses_non_frank': expenses_non_frank,
            'net_income': net_income,
            'total_transactions': sales.count(),
        },
        'daily_closes': closes_data,
        'barber_ranking': barber_ranking,
    })
