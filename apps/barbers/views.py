"""Barber views — public and admin APIs."""
from datetime import datetime, timedelta, time as dt_time

from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.http import JsonResponse
from apps.users.permissions import IsAdminOrAbove, IsBarberOrAbove, IsBatmanOrSuperadmin, IsAdminOrAboveWithWriteBatman
from apps.bookings.models import Booking, BlockedDate
from apps.services.models import Service
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
    GET /api/barbers/{id}/availability/?date=YYYY-MM-DD[&service_id=N]
    Devuelve los slots del día con su estado de disponibilidad.
    Si se pasa service_id, tiene en cuenta la duración del servicio para
    marcar como no disponibles los slots donde no cabe el servicio completo.
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

    # ── Duración del servicio seleccionado (default 30 min) ──────────────────
    # Frank usa siempre 2h por servicio, sin importar la duración nominal.
    SLOT_SIZE = 30  # cada bloque horario en el calendario = 30 min
    service_duration = SLOT_SIZE  # duración a reservar
    svc = None
    service_id = request.query_params.get('service_id')
    if service_id:
        try:
            svc = Service.objects.get(pk=service_id)
        except Service.DoesNotExist:
            svc = None
    if svc is not None:
        service_duration = barber.effective_duration_minutes(svc)
    elif barber.is_frank:
        # Sin servicio pero es Frank → todavía bloquea 2h por slot
        service_duration = 120

    # Cuántos bloques de 60 min ocupa este servicio (mínimo 1)
    slots_needed = max(1, -(-service_duration // SLOT_SIZE))  # ceil division

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
        bk_end = bk_start + timedelta(minutes=barber.occupied_minutes(bk_duration))
        booked_ranges.append((bk_start, bk_end))

    # Get barber-specific unavailability blocks for this date
    unavail_blocks = BarberUnavailability.objects.filter(
        barber=barber, date=target_date
    ).values_list('start_time', 'end_time')
    unavail_ranges = [
        (datetime.combine(target_date, s), datetime.combine(target_date, e))
        for s, e in unavail_blocks
    ]

    # ── Generar slots de 60 min ──────────────────────────────────────────────
    # Para cada slot verificamos que TODOS los bloques que necesita el servicio
    # estén libres. Ejemplo: Diamond VIP (120 min) a las 11:00 necesita
    # que tanto 11:00–12:00 como 12:00–13:00 estén disponibles.
    slots = []
    current = datetime.combine(target_date, start_time)
    end = datetime.combine(target_date, end_time)
    now_local = timezone.localtime()

    while current < end:
        slot_end = current + timedelta(minutes=SLOT_SIZE)
        # El servicio ocuparía desde current hasta current + service_duration
        service_end = current + timedelta(minutes=service_duration)

        is_available = True

        # 1. El servicio debe caber dentro del horario del barbero
        if service_end > end:
            is_available = False

        # 2. Verificar conflicto con reservas existentes para TODA la ventana del servicio
        if is_available:
            for br_start, br_end in booked_ranges:
                if current < br_end and service_end > br_start:
                    is_available = False
                    break

        # 3. Verificar conflicto con bloqueos manuales para TODA la ventana
        if is_available:
            for ur_start, ur_end in unavail_ranges:
                if current < ur_end and service_end > ur_start:
                    is_available = False
                    break

        # 4. Si es hoy, marcar horas pasadas como no disponibles
        if is_available and target_date == now_local.date() and current.time() <= now_local.time():
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
        'service_duration': service_duration,
        'slots_needed': slots_needed,
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

    # Detectar reservas activas que caigan dentro de la franja a bloquear.
    # No impedimos el bloqueo — solo devolvemos una advertencia para que el
    # barbero o admin contacte al cliente y reagende.
    block_start_dt = datetime.combine(d, s)
    block_end_dt = datetime.combine(d, e)
    conflicting = []
    for bk in Booking.objects.filter(
        barber=barber, date=d, status__in=['pending', 'confirmed']
    ).select_related('service'):
        bk_start = datetime.combine(d, bk.time)
        bk_end = bk_start + timedelta(minutes=barber.occupied_minutes(bk.duration_minutes))
        if block_start_dt < bk_end and block_end_dt > bk_start:
            conflicting.append(bk)

    u = BarberUnavailability.objects.create(
        barber=barber, date=d, start_time=s, end_time=e, reason=reason
    )

    response_data = {
        'id': u.id,
        'date': u.date.strftime('%Y-%m-%d'),
        'start_time': u.start_time.strftime('%H:%M'),
        'end_time': u.end_time.strftime('%H:%M'),
        'reason': u.reason,
    }
    if conflicting:
        detalles = ', '.join(
            f'{bk.client_name} a las {bk.time.strftime("%I:%M %p")}'
            for bk in conflicting
        )
        plural = 's' if len(conflicting) > 1 else ''
        response_data['warning'] = (
            f'Atención: ya hay {len(conflicting)} reserva{plural} agendada{plural} '
            f'con {barber.display_name} en esa franja '
            f'({s.strftime("%I:%M %p")}–{e.strftime("%I:%M %p")} del {d.strftime("%Y-%m-%d")}): '
            f'{detalles}. El bloqueo quedó aplicado, recuerda contactar al cliente '
            f'para reagendar.'
        )
    return Response(response_data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAdminOrAbove])
def barber_unavailability_bulk_create(request, barber_id):
    """
    POST /api/admin/barbers/{id}/unavailability/bulk/

    Crea bloqueos en lote para un rango de fechas. Útil para
    vacaciones, descansos largos o ausencias programadas.

    Body JSON:
      {
        date_from: 'YYYY-MM-DD',         # inclusivo
        date_to:   'YYYY-MM-DD',         # inclusivo
        all_day:   true,                  # opcional, default false
        start_time: 'HH:MM',              # requerido si !all_day
        end_time:   'HH:MM',              # requerido si !all_day
        weekdays:  [0,1,2,3,4,5,6],       # opcional, lunes=0 .. domingo=6
        reason:    'Vacaciones',          # opcional
      }

    Devuelve: { created, total_conflicts, days_with_conflicts,
                warnings: [string...], summary_warning?: string }.
    """
    barber = get_object_or_404(Barber, pk=barber_id)
    payload = request.data

    df_str = payload.get('date_from')
    dt_str = payload.get('date_to')
    all_day = bool(payload.get('all_day'))
    weekdays = payload.get('weekdays')
    reason = (payload.get('reason') or '').strip()

    if not df_str or not dt_str:
        return Response({'error': 'Faltan date_from y date_to.'},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        date_from = datetime.strptime(df_str, '%Y-%m-%d').date()
        date_to = datetime.strptime(dt_str, '%Y-%m-%d').date()
    except ValueError:
        return Response({'error': 'Formato de fecha inválido (use YYYY-MM-DD).'},
                        status=status.HTTP_400_BAD_REQUEST)

    if date_from > date_to:
        return Response({'error': 'La fecha inicial debe ser anterior o igual a la final.'},
                        status=status.HTTP_400_BAD_REQUEST)

    if (date_to - date_from).days > 365:
        return Response({'error': 'El rango no puede exceder 365 días.'},
                        status=status.HTTP_400_BAD_REQUEST)

    if all_day:
        from datetime import time as _time
        s = _time(0, 0, 0)
        # 23:59:59 cierra el último minuto del día — antes usábamos 23:59:00
        # y una reserva a las 23:59 (con duración > 0) no se detectaba como
        # solape porque el chequeo es u_end > req_start (estricto).
        e = _time(23, 59, 59)
    else:
        s_str = payload.get('start_time')
        e_str = payload.get('end_time')
        if not s_str or not e_str:
            return Response({'error': 'Faltan start_time y end_time (o use all_day=true).'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            s = datetime.strptime(s_str, '%H:%M').time()
            e = datetime.strptime(e_str, '%H:%M').time()
        except ValueError:
            return Response({'error': 'Formato de hora inválido (use HH:MM).'},
                            status=status.HTTP_400_BAD_REQUEST)
        if s >= e:
            return Response({'error': 'La hora desde debe ser anterior a la hora hasta.'},
                            status=status.HTTP_400_BAD_REQUEST)

    # Normalizar weekdays: si no viene o viene mal, asumir todos los días.
    if not isinstance(weekdays, list) or not weekdays:
        weekdays_set = {0, 1, 2, 3, 4, 5, 6}
    else:
        weekdays_set = set()
        for w in weekdays:
            try:
                wi = int(w)
                if 0 <= wi <= 6:
                    weekdays_set.add(wi)
            except (TypeError, ValueError):
                continue
        if not weekdays_set:
            return Response({'error': 'Selecciona al menos un día de la semana.'},
                            status=status.HTTP_400_BAD_REQUEST)

    # Iterar el rango y crear los bloqueos.
    created_ids = []
    conflicts_per_day = []
    cur = date_from
    one_day = timedelta(days=1)
    block_start_template_min = s.hour * 60 + s.minute
    block_end_template_min = e.hour * 60 + e.minute

    while cur <= date_to:
        if cur.weekday() not in weekdays_set:
            cur += one_day
            continue

        block_start_dt = datetime.combine(cur, s)
        block_end_dt = datetime.combine(cur, e)

        day_conflicts = []
        for bk in Booking.objects.filter(
            barber=barber, date=cur, status__in=['pending', 'confirmed']
        ):
            bk_start = datetime.combine(cur, bk.time)
            bk_end = bk_start + timedelta(minutes=barber.occupied_minutes(bk.duration_minutes))
            if block_start_dt < bk_end and block_end_dt > bk_start:
                day_conflicts.append(bk)

        u = BarberUnavailability.objects.create(
            barber=barber, date=cur, start_time=s, end_time=e, reason=reason
        )
        created_ids.append(u.id)

        if day_conflicts:
            names = ', '.join(
                f'{bk.client_name} ({bk.time.strftime("%I:%M %p")})'
                for bk in day_conflicts
            )
            conflicts_per_day.append({
                'date': cur.strftime('%d/%m/%Y'),
                'count': len(day_conflicts),
                'message': (
                    f'{cur.strftime("%d/%m/%Y")} ({len(day_conflicts)}): {names}'
                ),
            })

        cur += one_day

    total_conflicts = sum(c['count'] for c in conflicts_per_day)

    response_data = {
        'created': len(created_ids),
        'total_conflicts': total_conflicts,
        'days_with_conflicts': len(conflicts_per_day),
        'warnings': [c['message'] for c in conflicts_per_day],
    }
    if conflicts_per_day:
        response_data['summary_warning'] = (
            f'Se crearon {len(created_ids)} bloqueo(s). '
            f'{total_conflicts} reserva(s) en '
            f'{len(conflicts_per_day)} día(s) se cruzan con los bloqueos: contacta a los clientes para reagendar.'
        )
    return Response(response_data, status=status.HTTP_201_CREATED)


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
    permission_classes = [IsAdminOrAbove]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None


class GalleryAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PUT/DELETE /api/admin/gallery/{id}/"""
    queryset = GalleryImage.objects.all()
    serializer_class = GalleryImageSerializer
    permission_classes = [IsAdminOrAbove]
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
    permission_classes = [IsAdminOrAbove]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None


class ReelAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PUT/DELETE /api/admin/reels/{id}/"""
    queryset = Reel.objects.all()
    serializer_class = ReelSerializer
    permission_classes = [IsAdminOrAbove]
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

    profile = getattr(request.user, 'profile', None)
    es_operativo = bool(profile and profile.role in ('operational_admin', 'superadmin'))

    return render(request, 'barberos/dashboard.html', {
        'barbero': barbero,
        'citas': citas,
        'es_operativo': es_operativo,
    })


@login_required
def reservas_generales(request):
    """Apartado para el admin operativo (Frank): ver TODAS las reservas de todos
    los barberos y poder cancelarlas o reagendarlas.

    Reutiliza los endpoints existentes de /api/admin/bookings/ (que ya permiten al
    operational_admin ver todo, cancelar y reagendar). Acceso solo para el admin
    operativo o superadmin; cualquier otro barbero es redirigido a su agenda.
    """
    profile = getattr(request.user, 'profile', None)
    if not (profile and profile.role in ('operational_admin', 'superadmin')):
        return redirect('barbers_pages:dashboard_barbero')

    barbero = getattr(request.user, 'barber_profile', None)
    barbers = Barber.objects.all().order_by('display_name')

    return render(request, 'barberos/reservas_generales.html', {
        'barbero': barbero,
        'barbers': barbers,
    })


@login_required
def pagos_vales(request):
    """Apartado para el admin operativo (Frank): gestionar pagos y vales/adelantos
    de los barberos desde el área de barbero (sin entrar al panel admin completo).

    Reutiliza los endpoints de /api/admin/cashflow/barber-payments/ (que ya permiten
    al operational_admin ver, dar vales, anularlos y liquidar). Acceso solo para el
    admin operativo o superadmin; cualquier otro barbero es redirigido a su agenda.
    """
    profile = getattr(request.user, 'profile', None)
    if not (profile and profile.role in ('operational_admin', 'superadmin')):
        return redirect('barbers_pages:dashboard_barbero')

    barbero = getattr(request.user, 'barber_profile', None)
    return render(request, 'barberos/pagos_vales.html', {
        'barbero': barbero,
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

    # SEGURIDAD IDOR: validar que solo el barbero dueño de la cita pueda completarla.
    # Guardar contra None ANTES de desreferenciar cita.barber.user para no lanzar
    # AttributeError (500) en citas sin barbero asignado.
    barbero = getattr(request.user, 'barber_profile', None)
    if barbero is None or cita.barber is None or cita.barber.user != request.user:
        return JsonResponse({'ok': False, 'error': 'No autorizado para modificar esta cita'}, status=403)

    # No marcar 'completed': process_checkout (cashflow) rechaza reservas ya
    # 'completed' y la cita nunca podría facturarse (sin Sale, sin comisión).
    # Dejarla 'confirmed' la mantiene cobrable; completed_at registra la atención.
    cita.status = 'confirmed'
    cita.notes = observaciones

    # Fijar el timestamp de finalización para dejar constancia de que fue atendida
    cita.completed_at = timezone.now()

    cita.save()

    return JsonResponse({'ok': True})
