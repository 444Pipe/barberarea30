"""Analytics API — stats computed from booking data."""
from collections import defaultdict

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
    from datetime import date, timedelta
    from django.utils import timezone

    profile = getattr(request.user, 'profile', None)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    base = Booking.objects.all()

    # Barbers see only their own
    if profile and profile.is_barber and not profile.is_admin:
        barber = getattr(request.user, 'barber_profile', None)
        base = base.filter(barber=barber) if barber else base.none()

    completed = base.filter(status='completed')

    # Revenue toggles
    day_revenue = completed.filter(date=today).aggregate(r=Sum('price'))['r'] or 0
    week_revenue = completed.filter(date__gte=week_start).aggregate(r=Sum('price'))['r'] or 0
    month_revenue = completed.filter(date__gte=month_start).aggregate(r=Sum('price'))['r'] or 0

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
            'time': b.time.strftime('%H:%M'),
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
