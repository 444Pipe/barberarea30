"""Bookings views — public creation and admin CRUD with filters."""
import csv
from datetime import datetime

from django.http import HttpResponse, Http404
from django.utils import timezone
from django.core.signing import Signer, BadSignature
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages

from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.users.permissions import IsAdminOrAbove, IsBarberOrAbove, IsBatmanOrSuperadmin
from apps.users.decorators import staff_required
from apps.barbers.models import Barber
from apps.barbers.models import BarberUnavailability
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

    # 1b. Servicios "a consulta" no se reservan online.
    if service.requires_consultation:
        return Response({
            'error': (
                f'El servicio "{service.name}" es por consulta. '
                'Por favor contáctanos por WhatsApp para acordar fecha, '
                'precio y detalles.'
            ),
            'requires_consultation': True,
        }, status=400)

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

        # Parsear fecha/hora una sola vez antes del loop
        from datetime import datetime as _dt, timedelta
        date_val = date
        time_val = time
        try:
            req_d = _dt.strptime(date_val, '%Y-%m-%d').date()
            req_t = _dt.strptime(time_val, '%H:%M').time()
            req_start = _dt.combine(req_d, req_t)
            parsed_ok = True
        except (ValueError, TypeError):
            req_d = req_start = None
            parsed_ok = False

        # Buscar quién está libre (sin reservas NI bloqueos de inactividad).
        # OJO: la ventana del servicio depende del barbero (Frank usa 2h en
        # cualquier servicio), así que se recalcula req_end por candidato.
        for b in available_barbers:
            if parsed_ok:
                eff_dur = b.effective_duration_minutes(service)
                req_end = req_start + timedelta(minutes=eff_dur)

                # 1. Conflicto con reservas existentes (overlap real)
                conflicts = False
                for bk_time, bk_duration in Booking.objects.filter(
                    barber=b, date=date_val, status__in=['pending', 'confirmed']
                ).values_list('time', 'duration_minutes'):
                    bk_start = _dt.combine(req_d, bk_time)
                    bk_end = bk_start + timedelta(minutes=b.occupied_minutes(bk_duration))
                    if req_start < bk_end and req_end > bk_start:
                        conflicts = True
                        break
            else:
                conflicts = Booking.objects.filter(
                    barber=b, date=date_val, time=time_val, status__in=['pending', 'confirmed']
                ).exists()
                req_end = None

            if conflicts:
                continue

            # 2. Conflicto con inactividad temporal (solape real, no solo hora de inicio)
            blocked_now = False
            if parsed_ok:
                for u_start, u_end in BarberUnavailability.objects.filter(
                    barber=b, date=date_val
                ).values_list('start_time', 'end_time'):
                    u_s = _dt.combine(req_d, u_start)
                    u_e = _dt.combine(req_d, u_end)
                    if u_s < req_end and u_e > req_start:
                        blocked_now = True
                        break
            if blocked_now:
                continue

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
            # Validar inactividad temporal (solape real con la ventana del servicio)
            date_val = data.get('date')
            time_val = data.get('time')
            from datetime import datetime as _dt, timedelta as _td
            eff_dur = barber.effective_duration_minutes(service)
            try:
                slot_time = _dt.strptime(time_val, '%H:%M').time()
                req_d = _dt.strptime(date_val, '%Y-%m-%d').date()
                req_s = _dt.combine(req_d, slot_time)
                req_e = req_s + _td(minutes=eff_dur)
            except (ValueError, TypeError):
                req_s = req_e = req_d = None
            if req_s is not None:
                for u_start, u_end in BarberUnavailability.objects.filter(
                    barber=barber, date=date_val
                ).values_list('start_time', 'end_time'):
                    u_s = _dt.combine(req_d, u_start)
                    u_e = _dt.combine(req_d, u_end)
                    if u_s < req_e and u_e > req_s:
                        return Response({
                            'error': (
                                f'{barber.display_name} está bloqueado de '
                                f'{u_start.strftime("%I:%M %p")} a {u_end.strftime("%I:%M %p")} '
                                f'el {date_val}. Tu reserva ({time_val} – '
                                f'{req_e.strftime("%I:%M %p")}) se cruza con ese bloqueo. '
                                f'Por favor elige otra hora.'
                            )
                        }, status=409)
        except Barber.DoesNotExist:
            return Response({'error': 'Barbero no disponible'}, status=400)

    # ── Nivel 2: Validación explícita de doble agendamiento (Con overlaps) ───────────────────
    requested_date = data.get('date')
    requested_time_str = data.get('time')
    effective_duration = barber.effective_duration_minutes(service)
    try:
        from datetime import datetime as _dt, timedelta
        req_time = _dt.strptime(requested_time_str, '%H:%M').time()
        req_start = _dt.combine(_dt.strptime(requested_date, '%Y-%m-%d').date(), req_time)
        req_end = req_start + timedelta(minutes=effective_duration)

        # ── Nivel 2a: Validar bloqueos globales del local (BlockedDate) ─────────
        # Si la fecha tiene un BlockedDate sin horario → todo el día está cerrado.
        # Si tiene start_time/end_time → solo se atiende en esa franja; el
        # servicio completo debe caber adentro (start..end - duration).
        try:
            blocked = BlockedDate.objects.get(date=req_start.date())
        except BlockedDate.DoesNotExist:
            blocked = None

        if blocked is not None:
            if not blocked.start_time or not blocked.end_time:
                desc = f' ({blocked.description})' if blocked.description else ''
                return Response({
                    'ok': False,
                    'error': (
                        f'El {requested_date} la barbería está cerrada{desc}. '
                        f'Por favor elige otra fecha.'
                    )
                }, status=409)
            # Franja parcial: la reserva debe caber dentro de [start_time, end_time]
            if req_time < blocked.start_time or req_end.time() > blocked.end_time \
                    or req_end.date() != req_start.date():
                return Response({
                    'ok': False,
                    'error': (
                        f'El {requested_date} solo se atiende de '
                        f'{blocked.start_time.strftime("%I:%M %p")} a '
                        f'{blocked.end_time.strftime("%I:%M %p")}. '
                        f'El horario que elegiste no cabe en esa franja.'
                    )
                }, status=409)
        # ────────────────────────────────────────────────────────────────────────
        
        existing_bookings = Booking.objects.filter(
            barber=barber,
            date=requested_date,
            status__in=['pending', 'confirmed']
        ).values_list('time', 'duration_minutes')
        
        duplicate = False
        for bk_time, bk_duration in existing_bookings:
            bk_start = _dt.combine(_dt.strptime(requested_date, '%Y-%m-%d').date(), bk_time)
            bk_end = bk_start + timedelta(minutes=barber.occupied_minutes(bk_duration))

            if req_start < bk_end and req_end > bk_start:
                duplicate = True
                break
    except Exception:
        duplicate = Booking.objects.filter(
            barber=barber,
            date=requested_date,
            time=requested_time_str,
            status__in=['pending', 'confirmed'],
        ).exists()

    if duplicate:
        return Response({
            'ok': False,
            'error': (
                f'{barber.display_name} ya tiene una cita activa que se cruza con las '
                f'{requested_time_str} el {requested_date}. '
                f'Por favor elige otro horario u otro barbero.'
            )
        }, status=409)
    # ─────────────────────────────────────────────────────────────────────────

    serializer = BookingCreateSerializer(data=data)
    if serializer.is_valid():
        booking = serializer.save(
            barber=barber,
            service=service,
            price=data.get('price', service.price),
            duration_minutes=effective_duration,
        )

        import threading
        def send_emails_async():
            try:
                from django.db import connection
                from .emails import send_booking_confirmation_email, send_admin_new_booking_notification, send_barber_new_booking_notification
                send_booking_confirmation_email(booking)
                # Enviar notificación al admin local directamente para evitar el reenviador de Hostinger
                send_admin_new_booking_notification(booking)
                send_barber_new_booking_notification(booking)
            except Exception as e:
                print("Error enviando email:", e)
            finally:
                try:
                    from django.db import connection
                    connection.close()
                except Exception:
                    pass

        threading.Thread(target=send_emails_async).start()

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
    ).order_by('-created_at')[:6]

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
            'date': timezone.localtime(r.created_at).strftime('%d %b %Y'),
        })
    return Response({'reviews': data})

# ─── Admin ───────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsBarberOrAbove])
def admin_bookings_list_view(request):
    """GET /api/admin/bookings/ — lista con filtros avanzados."""
    profile = getattr(request.user, 'profile', None)
    queryset = Booking.objects.select_related('barber', 'service').all()

    # Barbers can only see their own bookings. Admins and operational_admins see all.
    if profile and profile.role not in ('admin', 'superadmin', 'operational_admin'):
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

    # Barber can only modify their own bookings. Admins and operational_admins can modify all.
    profile = getattr(request.user, 'profile', None)
    if profile and profile.role not in ('admin', 'superadmin', 'operational_admin'):
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

        if old_status == 'completed':
            if not (profile and profile.is_superadmin):
                return Response({'error': 'Esta reserva ya está pagada y bloqueada. No se permiten cambios.'}, status=403)

        if new_status != old_status:
            # Cancelar/reactivar reservas: superadmin y admin operativo (Frank).
            # Marcar como completada queda reservado a superadmin (ligado a ventas/comisiones).
            can_change_status = profile and (profile.is_superadmin or profile.is_operational_admin)
            if not can_change_status:
                return Response({'error': 'Solo los super administradores y el admin operativo pueden cambiar el estado de la reserva.'}, status=403)
            if new_status == 'completed' and not profile.is_superadmin:
                return Response({'error': 'Solo los super administradores pueden marcar una reserva como completada.'}, status=403)

        if new_status == 'completed' and old_status != 'completed':
            booking.completed_at = timezone.now()
            # Update barber's total cuts
            if booking.barber:
                booking.barber.total_cuts += 1
                booking.barber.save(update_fields=['total_cuts'])

        # Edición de campos básicos: permitida a superadmin y operational_admin (Frank)
        is_operational_or_super = profile and profile.role in ('superadmin', 'operational_admin')

        if 'status' in data:
            booking.status = data['status']
        if 'barber' in data and is_operational_or_super:
            booking.barber_id = data['barber']
        if 'notes' in data:
            booking.notes = data['notes']
        if 'date' in data and is_operational_or_super:
            booking.date = data['date']
        if 'time' in data and is_operational_or_super:
            booking.time = data['time']
        if 'client_name' in data and is_operational_or_super:
            booking.client_name = data['client_name']
        if 'client_phone' in data and is_operational_or_super:
            booking.client_phone = data['client_phone']
        if 'client_email' in data and is_operational_or_super:
            booking.client_email = data['client_email']
        if 'service' in data and is_operational_or_super:
            booking.service_id = data['service']
        if 'price' in data and is_operational_or_super:
            booking.price = data['price']

        # Si se está cambiando fecha, hora o barbero, validar bloqueos/inactividad.
        # Cancelaciones nunca se validan (un admin debe poder cancelar siempre).
        changed_slot = is_operational_or_super and any(
            k in data for k in ('date', 'time', 'barber', 'service')
        )
        # Recalcular duración efectiva si cambió barbero o servicio (Frank → 2h).
        if changed_slot and booking.barber:
            new_eff = booking.barber.effective_duration_minutes(booking.service)
            booking.duration_minutes = new_eff
            effective_dur_for_check = new_eff
        else:
            effective_dur_for_check = (
                booking.service.duration_minutes if booking.service else booking.duration_minutes
            )
        if changed_slot and booking.status not in ('cancelled', 'completed'):
            from .validators import check_booking_conflict
            err = check_booking_conflict(
                barber=booking.barber,
                date=booking.date,
                time=booking.time,
                duration_minutes=effective_dur_for_check,
                exclude_booking_id=booking.pk,
            )
            if err:
                return Response({'ok': False, 'error': err}, status=409)

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
        if not (profile and profile.is_superadmin):
            return Response({'error': 'Solo los super administradores pueden eliminar reservas permanentemente.'}, status=403)
        booking.delete()
        return Response({'ok': True}, status=204)

@api_view(['POST'])
@permission_classes([IsBarberOrAbove])
def admin_reschedule_booking_view(request, booking_id):
    """POST /api/admin/bookings/{id}/reschedule/ — Reagendar fecha y/u hora de una reserva."""
    profile = getattr(request.user, 'profile', None)
    is_operational_or_super = profile and profile.role in ('superadmin', 'operational_admin')
    if not is_operational_or_super:
        return Response({'error': 'Solo Franko y los super administradores pueden reagendar reservas.'}, status=403)

    try:
        booking = Booking.objects.select_related('barber', 'service').get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({'error': 'Reserva no encontrada'}, status=404)

    if booking.status == 'completed':
        return Response({'error': 'No se puede reagendar una reserva ya completada.'}, status=400)
    if booking.status == 'cancelled':
        return Response({'error': 'No se puede reagendar una reserva cancelada.'}, status=400)

    new_date = request.data.get('date', str(booking.date))
    new_time = request.data.get('time', booking.time.strftime('%H:%M'))

    from datetime import datetime as _dt, timedelta
    try:
        # Aceptar HH:MM o HH:MM:SS
        for fmt in ('%H:%M:%S', '%H:%M'):
            try:
                req_time = _dt.strptime(new_time, fmt).time()
                break
            except ValueError:
                continue
        else:
            raise ValueError(f'Hora inválida: {new_time}')
        req_date = _dt.strptime(new_date, '%Y-%m-%d').date()
        req_start = _dt.combine(req_date, req_time)
        _req_dur = booking.barber.occupied_minutes(booking.duration_minutes) if booking.barber else (booking.duration_minutes or 60)
        req_end = req_start + timedelta(minutes=_req_dur)
    except (ValueError, TypeError) as e:
        return Response({'error': f'Formato de fecha u hora inválido: {e}'}, status=400)

    # Validar bloqueo global del local (BlockedDate)
    try:
        blocked = BlockedDate.objects.get(date=req_date)
    except BlockedDate.DoesNotExist:
        blocked = None

    if blocked is not None:
        if not blocked.start_time or not blocked.end_time:
            desc = f' ({blocked.description})' if blocked.description else ''
            return Response({
                'ok': False,
                'error': (
                    f'El {new_date} la barbería está cerrada{desc}. '
                    f'No se puede reagendar a esa fecha.'
                )
            }, status=409)
        if req_time < blocked.start_time or req_end.time() > blocked.end_time \
                or req_end.date() != req_start.date():
            return Response({
                'ok': False,
                'error': (
                    f'El {new_date} solo se atiende de '
                    f'{blocked.start_time.strftime("%I:%M %p")} a '
                    f'{blocked.end_time.strftime("%I:%M %p")}. '
                    f'El nuevo horario no cabe en esa franja.'
                )
            }, status=409)

    # Validar inactividad temporal del barbero (BarberUnavailability)
    if booking.barber:
        from apps.barbers.models import BarberUnavailability as _BU
        unavail_qs = _BU.objects.filter(barber=booking.barber, date=req_date)
        for ur_start, ur_end in unavail_qs.values_list('start_time', 'end_time'):
            ur_s = _dt.combine(req_date, ur_start)
            ur_e = _dt.combine(req_date, ur_end)
            if req_start < ur_e and req_end > ur_s:
                return Response({
                    'ok': False,
                    'error': (
                        f'{booking.barber.display_name} tiene un bloqueo de inactividad '
                        f'de {ur_start.strftime("%I:%M %p")} a {ur_end.strftime("%I:%M %p")} '
                        f'el {new_date}. Por favor elige otra hora.'
                    )
                }, status=409)

    # Validar conflictos de horario (overlap)
    if booking.barber:
        conflict_qs = Booking.objects.filter(
            barber=booking.barber,
            date=req_date,
            status__in=['pending', 'confirmed'],
        ).exclude(pk=booking.pk)

        for bk in conflict_qs:
            # SQLite puede devolver strings en lugar de objetos date/time
            bk_d = bk.date if not isinstance(bk.date, str) else _dt.strptime(bk.date, '%Y-%m-%d').date()
            bk_t = bk.time if not isinstance(bk.time, str) else _dt.strptime(str(bk.time)[:5], '%H:%M').time()

            bk_start = _dt.combine(bk_d, bk_t)
            bk_end = bk_start + timedelta(minutes=booking.barber.occupied_minutes(bk.duration_minutes))
            if req_start < bk_end and req_end > bk_start:
                return Response({
                    'ok': False,
                    'error': (
                        f'{booking.barber.display_name} ya tiene una cita que se cruza con las '
                        f'{new_time} el {new_date}. Por favor elige otra hora.'
                    )
                }, status=409)

    old_date = str(booking.date)
    old_time = booking.time.strftime('%H:%M')

    booking.date = req_date
    booking.time = req_time
    booking.save(update_fields=['date', 'time'])

    # Registrar en auditoría
    if profile and profile.is_admin:
        try:
            from apps.analytics.models import log_audit
            log_audit(
                user=request.user,
                action='update',
                obj=booking,
                changes={'date': [old_date, new_date], 'time': [old_time, new_time]},
                request=request,
                extra_data={'msg': f'Reagendó la cita de {booking.client_name} de {old_date} {old_time} → {new_date} {new_time}'}
            )
        except Exception:
            pass

    serializer = BookingAdminSerializer(booking)
    return Response({'ok': True, 'booking': serializer.data})


@api_view(['GET'])
@permission_classes([IsAdminOrAbove])
def admin_bookings_export_csv(request):
    """GET /api/admin/bookings/export/ — exportar a CSV."""
    bookings = Booking.objects.select_related('barber', 'service').all()

    profile = getattr(request.user, 'profile', None)
    if profile and profile.role not in ('admin', 'superadmin'):
        barber_profile = getattr(request.user, 'barber_profile', None)
        if barber_profile:
            bookings = bookings.filter(barber=barber_profile)
        else:
            bookings = bookings.none()

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
            b.time.strftime('%I:%M %p'),
            b.price,
            b.get_status_display(),
            timezone.localtime(b.created_at).strftime('%Y-%m-%d %I:%M %p'),
        ])

    return response


@api_view(['DELETE'])
@permission_classes([IsBatmanOrSuperadmin])
def admin_delete_all_bookings_view(request):
    """DELETE /api/admin/bookings/bulk-delete/ — Eliminar todas las reservas."""
    return Response({'error': 'La eliminación masiva de reservas ha sido deshabilitada para preservar el historial de clientes de forma permanente.'}, status=403)


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


# ─── Public Client Booking Detail ──────────────────────────────────────────────

def client_booking_detail_view(request, signed_id):
    """
    Muestra los detalles de una reserva al cliente y permite cancelarla.
    Usa URLs firmadas para evitar que se adivinen IDs de otras personas.
    """
    from django.core.signing import Signer, BadSignature
    from django.shortcuts import render, get_object_or_404, redirect
    from django.http import Http404
    from django.contrib import messages

    signer = Signer()
    try:
        booking_id = signer.unsign(signed_id)
    except BadSignature:
        raise Http404("Enlace inválido o caducado.")
        
    booking = get_object_or_404(Booking, id=booking_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'cancel':
            if booking.can_cancel:
                booking.status = 'cancelled'
                booking.save()
                
                # Registrar en auditoría (aparece en el panel de notificaciones del admin)
                from apps.analytics.models import AuditLog
                AuditLog.objects.create(
                    user=None,  # Cliente anónimo
                    action='update',
                    model_name='Booking',
                    object_id=booking.id,
                    object_repr=str(booking),
                    changes={'status': ['pending/confirmed', 'cancelled']},
                    extra_data={
                        'msg': f'⚠️ {booking.client_name} canceló su reserva del {booking.date} a las {booking.time} con {booking.barber.display_name if booking.barber else "barbero"}.'
                    }
                )
                
                import threading
                def send_cancellation_emails_async(bk_id):
                    try:
                        from django.db import connection
                        from apps.bookings.models import Booking
                        bk = Booking.objects.get(pk=bk_id)
                        
                        from apps.bookings.emails import send_barber_cancellation_notification, _send_html_email
                        from django.conf import settings
                        send_barber_cancellation_notification(bk)
                        
                        # Usar directamente el correo del local para evitar reenvíos masivos de Hostinger
                        admin_emails = ['localarea30barberclub@gmail.com']
                        if admin_emails:
                            from django.core.mail import send_mail
                            from django.conf import settings as dj_settings
                            try:
                                send_mail(
                                    subject=f'⚠️ Cliente canceló cita — {bk.client_name}',
                                    message=(
                                        f'{bk.client_name} ha cancelado su reserva.\n'
                                        f'Fecha: {bk.date}\n'
                                        f'Hora: {bk.time}\n'
                                        f'Servicio: {bk.service.name if bk.service else "-"}\n'
                                        f'Barbero: {bk.barber.display_name if bk.barber else "-"}\n\n'
                                        f'Ingresa al panel para verificar.'
                                    ),
                                    from_email=dj_settings.DEFAULT_FROM_EMAIL,
                                    recipient_list=admin_emails,
                                    fail_silently=True,
                                )
                            except Exception:
                                pass
                    except Exception as e:
                        print("Error enviando correos de cancelación:", e)
                    finally:
                        try:
                            from django.db import connection
                            connection.close()
                        except Exception:
                            pass
                            
                threading.Thread(target=send_cancellation_emails_async, args=(booking.id,)).start()
                
                messages.success(request, "Tu reserva ha sido cancelada correctamente. Ya notificamos a tu barbero.")
            else:
                messages.error(request, "No puedes cancelar esta reserva. La cita ya pasó o está completada/cancelada.")
                
        return redirect('client_booking_detail', signed_id=signed_id)

    context = {
        'booking': booking,
    }
    return render(request, 'public/booking_detail.html', context)



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
