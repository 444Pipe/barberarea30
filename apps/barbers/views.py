"""Barber views — public and admin APIs."""
from datetime import datetime, timedelta, time as dt_time

from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.http import JsonResponse
from apps.users.permissions import IsAdminOrAbove, IsBarberOrAbove, IsBatmanOrSuperadmin, IsAdminOrAboveWithWriteBatman
from apps.bookings.models import Booking, BlockedDate
from .models import Barber, GalleryImage, Reel, BarberUnavailability
from .serializers import BarberListSerializer, BarberAdminSerializer, GalleryImageSerializer, ReelSerializer


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

    # Check global BlockedDate for overrides
    try:
        blocked = BlockedDate.objects.get(date=target_date)
        if blocked.start_time and blocked.end_time:
            start_time = blocked.start_time
            end_time = blocked.end_time
        else:
            return Response({
                'barber_id': barber.id,
                'barber_name': barber.display_name,
                'date': date_str,
                'day_off': True,
                'slots': [],
            })
    except BlockedDate.DoesNotExist:
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

    # Get barber-specific unavailability blocks for this date
    unavail_blocks = BarberUnavailability.objects.filter(
        barber=barber, date=target_date
    ).values_list('start_time', 'end_time')
    unavail_ranges = [
        (datetime.combine(target_date, s), datetime.combine(target_date, e))
        for s, e in unavail_blocks
    ]

    # Generate 60-minute slots
    slots = []
    current = datetime.combine(target_date, start_time)
    end = datetime.combine(target_date, end_time)

    while current < end:
        slot_end = current + timedelta(minutes=60)
        is_available = True

        for br_start, br_end in booked_ranges:
            if current < br_end and slot_end > br_start:
                is_available = False
                break

        if is_available:
            for ur_start, ur_end in unavail_ranges:
                if current < ur_end and slot_end > ur_start:
                    is_available = False
                    break

        # If date is today, mark past times as unavailable
        now_local = timezone.localtime()
        if target_date == now_local.date() and current.time() <= now_local.time():
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
    permission_classes = [IsAdminOrAboveWithWriteBatman]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        barber = serializer.save()
        # Retornar credenciales generadas junto con los datos del barbero
        response_data = serializer.data
        response_data = dict(response_data)
        response_data['created_username'] = getattr(barber, '_created_username', barber.user.username)
        response_data['created_password'] = getattr(barber, '_created_password', '')
        return Response(response_data, status=status.HTTP_201_CREATED)


class BarberAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PUT/DELETE /api/admin/barbers/{id}/"""
    queryset = Barber.objects.all()
    serializer_class = BarberAdminSerializer
    permission_classes = [IsAdminOrAboveWithWriteBatman]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


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
import json

def obtener_barberos_nativos(request):
    """Endpoint nativo de barberos para JS Vanilla"""
    barberos_qs = Barber.objects.filter(is_available=True).prefetch_related('specialties')
    barberos = []
    for b in barberos_qs:
        especialidades = ', '.join([s.name for s in b.specialties.all()])
        barberos.append({
            'id': b.id,
            'nombre': b.display_name,
            'especialidad': especialidades,
            'avatar': b.avatar.url if b.avatar else None,
        })
    return JsonResponse({'barberos': barberos}, safe=False)


# ─── Barber Unavailability ────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAdminOrAbove])
def barber_unavailability_list(request, barber_id):
    """
    GET  /api/admin/barbers/{id}/unavailability/ — lista bloqueos
    POST /api/admin/barbers/{id}/unavailability/ — crear bloqueo
    Body JSON: {date, start_time, end_time, reason?}
    """
    barber = get_object_or_404(Barber, pk=barber_id)

    if request.method == 'GET':
        items = BarberUnavailability.objects.filter(barber=barber)
        data = [{
            'id': u.id,
            'date': u.date.strftime('%Y-%m-%d'),
            'start_time': u.start_time.strftime('%H:%M'),
            'end_time': u.end_time.strftime('%H:%M'),
            'reason': u.reason,
        } for u in items]
        return Response(data)

    # POST
    payload = request.data
    date_str = payload.get('date')
    start_str = payload.get('start_time')
    end_str = payload.get('end_time')
    reason = payload.get('reason', '')

    if not (date_str and start_str and end_str):
        return Response({'error': 'Faltan campos: date, start_time, end_time'},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        from datetime import date as _date, time as _time
        d = datetime.strptime(date_str, '%Y-%m-%d').date()
        s = datetime.strptime(start_str, '%H:%M').time()
        e = datetime.strptime(end_str, '%H:%M').time()
    except ValueError:
        return Response({'error': 'Formato incorrecto. Use YYYY-MM-DD y HH:MM'},
                        status=status.HTTP_400_BAD_REQUEST)

    if s >= e:
        return Response({'error': 'La hora de inicio debe ser anterior a la de fin'},
                        status=status.HTTP_400_BAD_REQUEST)

    u = BarberUnavailability.objects.create(
        barber=barber, date=d, start_time=s, end_time=e, reason=reason
    )
    return Response({
        'id': u.id,
        'date': u.date.strftime('%Y-%m-%d'),
        'start_time': u.start_time.strftime('%H:%M'),
        'end_time': u.end_time.strftime('%H:%M'),
        'reason': u.reason,
    }, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAdminOrAbove])
def barber_unavailability_delete(request, barber_id, unavail_id):
    """DELETE /api/admin/barbers/{id}/unavailability/{uid}/"""
    u = get_object_or_404(BarberUnavailability, pk=unavail_id, barber_id=barber_id)
    u.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# ─── Gallery ─────────────────────────────────────────────

class GalleryPublicListView(generics.ListAPIView):
    """GET /api/gallery/ — lista pública de imágenes."""
    queryset = GalleryImage.objects.select_related('barber').all()
    serializer_class = GalleryImageSerializer
    permission_classes = [AllowAny]
    pagination_class = None


class GalleryAdminListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/admin/gallery/"""
    queryset = GalleryImage.objects.select_related('barber').all()
    serializer_class = GalleryImageSerializer
    permission_classes = [IsBarberOrAbove]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None


class GalleryAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PUT/DELETE /api/admin/gallery/{id}/"""
    queryset = GalleryImage.objects.all()
    serializer_class = GalleryImageSerializer
    permission_classes = [IsBarberOrAbove]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


# ─── Reels ──────────────────────────────────────────────

class ReelPublicListView(generics.ListAPIView):
    """GET /api/reels/ — lista pública de reels activos."""
    queryset = Reel.objects.filter(is_active=True).select_related('barber')
    serializer_class = ReelSerializer
    permission_classes = [AllowAny]
    pagination_class = None


class ReelAdminListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/admin/reels/ — lista completa y subir reel."""
    queryset = Reel.objects.all().select_related('barber')
    serializer_class = ReelSerializer
    permission_classes = [IsBarberOrAbove]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None


class ReelAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PUT/DELETE /api/admin/reels/{id}/"""
    queryset = Reel.objects.all()
    serializer_class = ReelSerializer
    permission_classes = [IsBarberOrAbove]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


# ─── Dashboard Barberos (Panel Web) ──────────────────────

@login_required
def dashboard_barbero(request):
    """Vista para el panel privado del barbero.
    Lista sus reservas pendientes/confirmadas del día o futuras.
    """
    try:
        barbero = request.user.barber_profile
    except Barber.DoesNotExist:
        # En caso de que un admin u otro rol sin perfil de barbero ingrese
        return render(request, 'barberos/dashboard.html', {
            'error_perfil': True
        })

    # Citas asignadas al barbero en estado pendente o confirmado
    citas = Booking.objects.filter(
        barber=barbero,
        status__in=['pending', 'confirmed']
    ).order_by('date', 'time')

    return render(request, 'barberos/dashboard.html', {
        'barbero': barbero,
        'citas': citas,
    })


@login_required
@require_POST
def finalizar_cita(request):
    """Endpoint llamado por el dashboard del barbero al finalizar una cita."""
    cita_id = request.POST.get('cita_id')
    observaciones = request.POST.get('observaciones', '').strip()
    
    if not observaciones:
        observaciones = 'Sin observaciones'

    cita = get_object_or_404(Booking, id=cita_id)

    # SEGURIDAD IDOR: validar que solo el barbero dueño de la cita pueda completarla
    if not hasattr(request.user, 'barber_profile') or cita.barber.user != request.user:
        return JsonResponse({'ok': False, 'error': 'No autorizado para modificar esta cita'}, status=403)

    cita.status = 'completed'
    cita.notes = observaciones
    
    # También fijar el timestamp de finalización usando datetime.now
    cita.completed_at = timezone.now()
    
    cita.save()
    
    return JsonResponse({'ok': True})
