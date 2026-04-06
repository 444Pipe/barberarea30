"""Bookings views — public creation and admin CRUD with filters."""
import csv
from datetime import datetime

from django.http import HttpResponse
from django.utils import timezone

from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.users.permissions import IsAdminOrAbove, IsBarberOrAbove
from apps.barbers.models import Barber
from apps.services.models import Service
from .models import Booking, BlockedDate
from .serializers import BookingCreateSerializer, BookingAdminSerializer, BlockedDateSerializer


# ─── Public ──────────────────────────────────────────────

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def public_blocked_dates_list(request):
    """GET /api/blocked-dates/ — listar fechas bloqueadas para el frontend."""
    try:
        blocked = BlockedDate.objects.filter(date__gte=timezone.now().date())
        serializer = BlockedDateSerializer(blocked, many=True)
        return Response(serializer.data)
    except Exception as e:
        import traceback
        from django.http import JsonResponse
        return JsonResponse({
            'ok': False, 
            'error': str(e), 
            'trace': traceback.format_exc()
        }, status=500)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def create_booking_view(request):
    """POST /api/bookings/ — crear nueva reserva desde el frontend público."""
    data = request.data

    # Validate barber and service
    try:
        barber = Barber.objects.get(pk=data.get('barber_id'), is_available=True)
    except Barber.DoesNotExist:
        return Response({'error': 'Barbero no disponible'}, status=400)

    try:
        service = Service.objects.get(pk=data.get('service_id'), is_active=True)
    except Service.DoesNotExist:
        return Response({'error': 'Servicio no válido'}, status=400)

    serializer = BookingCreateSerializer(data=data)
    if serializer.is_valid():
        booking = serializer.save(
            barber=barber,
            service=service,
            price=data.get('price', service.price),
            duration_minutes=service.duration_minutes,
        )
        return Response({
            'ok': True,
            'id': booking.id,
            'message': 'Reserva creada exitosamente'
        }, status=201)

    return Response({'ok': False, 'errors': serializer.errors}, status=400)


# ─── Admin ───────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsBarberOrAbove])
def admin_bookings_list_view(request):
    """GET /api/admin/bookings/ — lista con filtros avanzados."""
    profile = getattr(request.user, 'profile', None)
    queryset = Booking.objects.select_related('barber', 'service').all()

    # Barbers can only see their own bookings
    if profile and profile.is_barber and not profile.is_admin:
        barber_profile = getattr(request.user, 'barber_profile', None)
        if barber_profile:
            queryset = queryset.filter(barber=barber_profile)
        else:
            queryset = queryset.none()

    # Filters
    barber_id = request.query_params.get('barber')
    if barber_id:
        queryset = queryset.filter(barber_id=barber_id)

    status_filter = request.query_params.get('status')
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    service_id = request.query_params.get('service')
    if service_id:
        queryset = queryset.filter(service_id=service_id)

    date_from = request.query_params.get('date_from')
    if date_from:
        queryset = queryset.filter(date__gte=date_from)

    date_to = request.query_params.get('date_to')
    if date_to:
        queryset = queryset.filter(date__lte=date_to)

    search = request.query_params.get('search')
    if search:
        from django.db.models import Q
        queryset = queryset.filter(
            Q(client_name__icontains=search) | Q(client_phone__icontains=search)
        )

    serializer = BookingAdminSerializer(queryset[:200], many=True)
    return Response(serializer.data)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsBarberOrAbove])
def admin_booking_detail_view(request, booking_id):
    """GET/PATCH/DELETE /api/admin/bookings/{id}/"""
    try:
        booking = Booking.objects.select_related('barber', 'service').get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({'error': 'Reserva no encontrada'}, status=404)

    # Barber can only modify their own bookings
    profile = getattr(request.user, 'profile', None)
    if profile and profile.is_barber and not profile.is_admin:
        barber_profile = getattr(request.user, 'barber_profile', None)
        if booking.barber != barber_profile:
            return Response({'error': 'Sin permisos'}, status=403)

    if request.method == 'GET':
        serializer = BookingAdminSerializer(booking)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        data = request.data

        # Track status changes
        old_status = booking.status
        new_status = data.get('status', old_status)

        if new_status == 'completed' and old_status != 'completed':
            booking.completed_at = timezone.now()
            # Update barber's total cuts
            if booking.barber:
                booking.barber.total_cuts += 1
                booking.barber.save(update_fields=['total_cuts'])

        # Allow updating status, barber, notes
        if 'status' in data:
            booking.status = data['status']
        if 'barber' in data:
            booking.barber_id = data['barber']
        if 'notes' in data:
            booking.notes = data['notes']
        if 'date' in data:
            booking.date = data['date']
        if 'time' in data:
            booking.time = data['time']

        booking.save()
        serializer = BookingAdminSerializer(booking)
        return Response(serializer.data)

    elif request.method == 'DELETE':
        booking.delete()
        return Response({'ok': True}, status=204)


@api_view(['GET'])
@permission_classes([IsAdminOrAbove])
def admin_bookings_export_csv(request):
    """GET /api/admin/bookings/export/ — exportar a CSV."""
    bookings = Booking.objects.select_related('barber', 'service').all()

    # Aplicar mismos filtros que la lista
    barber_id = request.query_params.get('barber')
    if barber_id:
        bookings = bookings.filter(barber_id=barber_id)
    status_filter = request.query_params.get('status')
    if status_filter:
        bookings = bookings.filter(status=status_filter)
    date_from = request.query_params.get('date_from')
    if date_from:
        bookings = bookings.filter(date__gte=date_from)
    date_to = request.query_params.get('date_to')
    if date_to:
        bookings = bookings.filter(date__lte=date_to)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="reservas_area30.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'Cliente', 'Teléfono', 'Email', 'Servicio', 'Barbero',
                     'Fecha', 'Hora', 'Precio', 'Estado', 'Creado'])

    for b in bookings:
        writer.writerow([
            b.id,
            b.client_name,
            b.client_phone,
            b.client_email,
            b.service.name if b.service else '',
            b.barber.display_name if b.barber else '',
            b.date.strftime('%Y-%m-%d'),
            b.time.strftime('%H:%M'),
            b.price,
            b.get_status_display(),
            b.created_at.strftime('%Y-%m-%d %H:%M'),
        ])

    return response


# ─── Admin Blocked Dates ─────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAdminOrAbove])
def admin_blocked_dates_view(request):
    """GET/POST /api/admin/blocked-dates/"""
    if request.method == 'GET':
        blocked = BlockedDate.objects.all().order_by('-date') # Recientes primero
        serializer = BlockedDateSerializer(blocked, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        serializer = BlockedDateSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


@api_view(['DELETE'])
@permission_classes([IsAdminOrAbove])
def admin_blocked_date_detail_view(request, pk):
    """DELETE /api/admin/blocked-dates/{id}/"""
    try:
        blocked = BlockedDate.objects.get(pk=pk)
        blocked.delete()
        return Response({'ok': True}, status=204)
    except BlockedDate.DoesNotExist:
        return Response({'error': 'No encontrado'}, status=404)
