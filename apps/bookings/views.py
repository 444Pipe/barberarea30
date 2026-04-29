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
from django.views.generic import TemplateView

class HomeView(TemplateView):
    """Renderiza la página principal con el listado de profesionales dinámico."""
    template_name = 'public/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Obtenemos los barberos disponibles y los ordenamos
        context['barbers'] = Barber.objects.filter(is_available=True).order_by('display_order', 'display_name')
        return context

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
    
    is_walk_in = str(data.get('is_walk_in', '')).lower() == 'true'
    if is_walk_in:
        data['client_name'] = data.get('client_name') or 'Cliente General'
        data['privacy_accepted'] = True  # Admin creating walk-ins overrides this
    else:
        # Require explicit privacy acceptance for regular booking
        if str(data.get('privacy_accepted', '')).lower() != 'true':
            return Response({'error': 'Debe aceptar los términos y condiciones (Habeas Data).'}, status=400)
    
    # 1. Validar servicio
    try:
        service = Service.objects.get(pk=data.get('service_id'), is_active=True)
    except Service.DoesNotExist:
        return Response({'error': 'Servicio no válido'}, status=400)

    # 2. Lógica "Cualquier barbero" vs barbero específico
    barber_id = data.get('barber_id')
    barber = None
    
    if not barber_id or str(barber_id).lower() == 'any':
        date = data.get('date')
        time = data.get('time')
        
        # Encontrar un barbero disponible
        # Primero, buscamos todos los barberos activos
        available_barbers = Barber.objects.filter(is_available=True)
        
        # Si el servicio excluye barberos (exclusive_barber), solo considerar el asignado o fallar
        if service.exclusive_barber:
            available_barbers = available_barbers.filter(id=service.exclusive_barber.id)
            if not available_barbers.exists():
                return Response({'error': 'El barbero asignado para este servicio exclusivo no está disponible.'}, status=400)

        # Buscar quién está libre
        for b in available_barbers:
            # Check si b está libre en `date` y `time`
            conflicts = Booking.objects.filter(
                barber=b, date=date, time=time, status__in=['pending', 'confirmed']
            ).exists()
            if not conflicts:
                barber = b
                break
                
        if not barber:
            return Response({'error': 'No hay barberos disponibles en la franja horaria seleccionada.'}, status=400)
    else:
        try:
            barber = Barber.objects.get(pk=barber_id, is_available=True)
            # Validar servicio exclusivo
            if service.exclusive_barber and service.exclusive_barber.id != barber.id:
                return Response({'error': 'Este servicio exclusivo solo puede ser realizado por otro barbero.'}, status=400)
        except Barber.DoesNotExist:
            return Response({'error': 'Barbero no disponible'}, status=400)

    serializer = BookingCreateSerializer(data=data)
    if serializer.is_valid():
        booking = serializer.save(
            barber=barber,
            service=service,
            price=data.get('price', service.price),
            duration_minutes=service.duration_minutes,
        )

        try:
            from .emails import send_booking_confirmation_email
            send_booking_confirmation_email(booking)
        except Exception as e:
            print("Error enviando email:", e)

        return Response({
            'ok': True,
            'id': booking.id,
            'barber_assigned': barber.id,
            'barber_name': barber.display_name,
            'message': 'Reserva creada exitosamente'
        }, status=201)

    return Response({'ok': False, 'errors': serializer.errors}, status=400)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def cancel_booking_view(request, booking_id):
    """POST /api/bookings/{id}/cancel/ - Endpoint público para cancelar cita si faltan > 2 horas."""
    try:
        booking = Booking.objects.get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({'error': 'Reserva no encontrada'}, status=404)
        
    if not booking.can_cancel:
        return Response({'error': 'No se puede cancelar la cita con menos de 2 horas de anticipación.'}, status=400)
        
    booking.status = 'cancelled'
    booking.save()
    
    return Response({'ok': True, 'message': 'Cita cancelada exitosamente.'})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def add_review_view(request, booking_id):
    """POST /api/bookings/{id}/review/ - Envia calificación de 1 a 5 para barbero y local."""
    from .models import Review
    from django.db.models import Avg

    try:
        booking = Booking.objects.get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({'error': 'Reserva no encontrada'}, status=404)

    if booking.status != 'completed':
        return Response({'error': 'Solo se pueden calificar servicios completados.'}, status=400)

    if hasattr(booking, 'review'):
        return Response({'error': 'Esta reserva ya tiene una calificación.'}, status=400)

    barber_rating = int(request.data.get('barber_rating', 5))
    shop_rating = int(request.data.get('shop_rating', 5))
    comment = request.data.get('comment', '')

    review = Review.objects.create(
        booking=booking,
        barber_rating=barber_rating,
        shop_rating=shop_rating,
        comment=comment
    )

    # Actualizar promedio del barbero
    if booking.barber:
        reviews = Review.objects.filter(booking__barber=booking.barber)
        avg = reviews.aggregate(Avg('barber_rating'))['barber_rating__avg']
        booking.barber.rating = round(avg, 1)
        booking.barber.save()

    return Response({'ok': True, 'message': 'Calificación guardada exitosamente.'})

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def add_suggestion_view(request):
    """POST /api/suggestions/ - Guarda una sugerencia pública."""
    from .models import Suggestion
    
    name = request.data.get('name', '')
    email = request.data.get('email', '')
    message = request.data.get('message', '').strip()
    
    if not message:
        return Response({'error': 'El mensaje no puede estar vacío.'}, status=400)
        
    Suggestion.objects.create(name=name, email=email, message=message)
    return Response({'ok': True, 'message': 'Sugerencia enviada correctamente.'})


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def public_reviews_view(request):
    """GET /api/reviews/ — Retorna las reseñas públicas (barber_rating >= 4) para el index."""
    from .models import Review
    reviews = Review.objects.select_related(
        'booking__barber', 'booking__service'
    ).filter(
        is_public=True, barber_rating__gte=4
    ).order_by('-created_at')[:12]

    data = []
    for r in reviews:
        barber_name = None
        if r.booking.barber:
            barber_name = r.booking.barber.display_name
        data.append({
            'client_name': r.booking.client_name,
            'barber_name': barber_name,
            'service_name': r.booking.service.name if r.booking.service else None,
            'barber_rating': r.barber_rating,
            'shop_rating': r.shop_rating,
            'comment': r.comment,
            'date': r.created_at.strftime('%d %b %Y'),
        })
    return Response({'reviews': data})

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
        
        # Audit Log para cambios de estado (ej: cancelado)
        if new_status != old_status and profile and profile.is_admin:
            from apps.analytics.models import log_audit
            msg = f"Cambió el estado de la reserva de {booking.client_name} a {new_status}"
            log_audit(
                user=request.user,
                action='update',
                obj=booking,
                changes={'status': [old_status, new_status]},
                request=request,
                extra_data={'msg': msg}
            )
            
        serializer = BookingAdminSerializer(booking)
        return Response(serializer.data)

    elif request.method == 'DELETE':
        client_name = booking.client_name
        booking.delete()
        if profile and profile.is_admin:
            from apps.analytics.models import log_audit
            log_audit(
                user=request.user,
                action='delete',
                obj=None,
                changes={},
                request=request,
                extra_data={'msg': f"Eliminó la reserva de {client_name}"}
            )
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


@api_view(['DELETE'])
@permission_classes([IsAdminOrAbove])
def admin_delete_all_bookings_view(request):
    """DELETE /api/admin/bookings/bulk-delete/ — Eliminar todas las reservas."""
    Booking.objects.all().delete()
    from apps.analytics.models import log_audit
    log_audit(
        user=request.user,
        action='delete',
        obj=None,
        changes={},
        request=request,
        extra_data={'msg': "Eliminó TODAS las reservas del sistema"}
    )
    return Response({'ok': True, 'message': 'Todas las reservas eliminadas'}, status=204)


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


@api_view(['DELETE'])
@permission_classes([IsAdminOrAbove])
def admin_delete_review_view(request, pk):
    """DELETE /api/admin/reviews/{id}/ — Elimina una reseña individual."""
    from .models import Review
    from django.db.models import Avg
    try:
        review = Review.objects.select_related('booking__barber').get(pk=pk)
        barber = review.booking.barber if review.booking else None
        review.delete()
        # Recalculate barber's average after deletion
        if barber:
            reviews_remaining = Review.objects.filter(booking__barber=barber)
            avg = reviews_remaining.aggregate(Avg('barber_rating'))['barber_rating__avg']
            barber.rating = round(avg, 1) if avg else 0
            barber.save()
        return Response({'ok': True}, status=204)
    except Review.DoesNotExist:
        return Response({'error': 'Reseña no encontrada'}, status=404)
