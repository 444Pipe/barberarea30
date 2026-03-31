"""Barber views — public and admin APIs."""
from datetime import datetime, timedelta, time as dt_time

from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.users.permissions import IsAdminOrAbove
from apps.bookings.models import Booking
from .models import Barber
from .serializers import BarberListSerializer, BarberAdminSerializer


# ─── Public ──────────────────────────────────────────────

class BarberPublicListView(generics.ListAPIView):
    """GET /api/barbers/ — lista pública de barberos activos."""
    queryset = Barber.objects.filter(is_available=True).prefetch_related('specialties')
    serializer_class = BarberListSerializer
    permission_classes = [AllowAny]
    pagination_class = None


@api_view(['GET'])
@permission_classes([AllowAny])
def barber_availability_view(request, barber_id):
    """
    GET /api/barbers/{id}/availability/?date=YYYY-MM-DD
    Devuelve los slots del día con su estado de disponibilidad.
    """
    date_str = request.query_params.get('date')
    if not date_str:
        return Response({'error': 'Parámetro date requerido (YYYY-MM-DD)'},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response({'error': 'Formato de fecha inválido. Use YYYY-MM-DD'},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        barber = Barber.objects.get(pk=barber_id, is_available=True)
    except Barber.DoesNotExist:
        return Response({'error': 'Barbero no encontrado'},
                        status=status.HTTP_404_NOT_FOUND)

    # Map weekday number to schedule key
    day_names = ['monday', 'tuesday', 'wednesday', 'thursday',
                 'friday', 'saturday', 'sunday']
    day_key = day_names[target_date.weekday()]
    day_schedule = barber.schedule.get(day_key)

    if not day_schedule:
        return Response({
            'barber_id': barber.id,
            'barber_name': barber.display_name,
            'date': date_str,
            'day_off': True,
            'slots': [],
        })

    # Parse start and end times
    start_time = datetime.strptime(day_schedule['start'], '%H:%M').time()
    end_time = datetime.strptime(day_schedule['end'], '%H:%M').time()

    # Get existing bookings for this barber on this date
    booked = Booking.objects.filter(
        barber=barber, date=target_date
    ).exclude(status='cancelled').values_list('time', 'duration_minutes')

    booked_ranges = []
    for bk_time, bk_duration in booked:
        bk_start = datetime.combine(target_date, bk_time)
        bk_end = bk_start + timedelta(minutes=bk_duration or 60)
        booked_ranges.append((bk_start, bk_end))

    # Generate 30-minute slots
    slots = []
    current = datetime.combine(target_date, start_time)
    end = datetime.combine(target_date, end_time)

    while current < end:
        slot_end = current + timedelta(minutes=30)
        is_available = True
        for br_start, br_end in booked_ranges:
            if current < br_end and slot_end > br_start:
                is_available = False
                break

        # If date is today, mark past times as unavailable
        now = datetime.now()
        if target_date == now.date() and current.time() <= now.time():
            is_available = False

        slots.append({
            'time': current.strftime('%H:%M'),
            'available': is_available,
        })
        current = slot_end

    total_slots = len(slots)
    available_count = sum(1 for s in slots if s['available'])

    if available_count == 0:
        availability_status = 'unavailable'
    elif available_count < total_slots * 0.3:
        availability_status = 'partial'
    else:
        availability_status = 'available'

    return Response({
        'barber_id': barber.id,
        'barber_name': barber.display_name,
        'date': date_str,
        'day_off': False,
        'availability_status': availability_status,
        'available_count': available_count,
        'total_slots': total_slots,
        'slots': slots,
    })


# ─── Admin ───────────────────────────────────────────────

class BarberAdminListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/admin/barbers/ — lista con stats y crear barbero."""
    queryset = Barber.objects.all().prefetch_related('specialties')
    serializer_class = BarberAdminSerializer
    permission_classes = [IsAdminOrAbove]
    pagination_class = None


class BarberAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PUT/DELETE /api/admin/barbers/{id}/"""
    queryset = Barber.objects.all()
    serializer_class = BarberAdminSerializer
    permission_classes = [IsAdminOrAbove]


@api_view(['GET'])
@permission_classes([IsAdminOrAbove])
def barber_stats_view(request, barber_id):
    """GET /api/admin/barbers/{id}/stats/ — estadísticas individuales."""
    try:
        barber = Barber.objects.get(pk=barber_id)
    except Barber.DoesNotExist:
        return Response({'error': 'Barbero no encontrado'}, status=404)

    from django.db.models import Sum, Count, Avg

    bookings = Booking.objects.filter(barber=barber)
    completed = bookings.filter(status='completed')

    stats = completed.aggregate(
        total_revenue=Sum('price'),
        total_bookings=Count('id'),
        avg_ticket=Avg('price'),
    )

    # Unique clients
    unique_clients = completed.values('client_phone').distinct().count()

    # Top services
    top_services = (
        completed.values('service__name')
        .annotate(count=Count('id'))
        .order_by('-count')[:5]
    )

    return Response({
        'barber_id': barber.id,
        'barber_name': barber.display_name,
        'total_revenue': stats['total_revenue'] or 0,
        'total_bookings': stats['total_bookings'] or 0,
        'avg_ticket': round(stats['avg_ticket'] or 0),
        'unique_clients': unique_clients,
        'top_services': list(top_services),
    })

from django.http import JsonResponse

def obtener_barberos_nativos(request):
    """Endpoint nativo de barberos para JS Vanilla"""
    barberos_qs = Barber.objects.filter(is_available=True).prefetch_related('specialties')
    barberos = []
    for b in barberos_qs:
        especialidades = ', '.join([s.name for s in b.specialties.all()])
        barberos.append({
            'id': b.id,
            'nombre': b.display_name,
            'especialidad': especialidades
        })
    return JsonResponse({'barberos': barberos}, safe=False)
