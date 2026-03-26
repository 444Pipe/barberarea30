"""Clients API — aggregated from bookings."""
from django.db.models import Count, Sum, Max

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.users.permissions import IsAdminOrAbove
from apps.bookings.models import Booking


@api_view(['GET'])
@permission_classes([IsAdminOrAbove])
def clients_list_view(request):
    """GET /api/admin/clients/ — lista de clientes únicos."""
    clients = (
        Booking.objects.exclude(status='cancelled')
        .values('client_phone', 'client_name', 'client_email')
        .annotate(
            total_visits=Count('id'),
            total_spent=Sum('price'),
            last_visit=Max('date'),
        )
        .order_by('-last_visit')
    )

    search = request.query_params.get('search')
    if search:
        from django.db.models import Q
        clients = clients.filter(
            Q(client_name__icontains=search) | Q(client_phone__icontains=search)
        )

    # Add preferred barber for each client
    result = []
    for client in clients[:100]:
        # Get most visited barber
        preferred = (
            Booking.objects.filter(client_phone=client['client_phone'])
            .exclude(status='cancelled')
            .values('barber__display_name')
            .annotate(count=Count('id'))
            .order_by('-count')
            .first()
        )
        result.append({
            'name': client['client_name'],
            'phone': client['client_phone'],
            'email': client['client_email'] or '',
            'total_visits': client['total_visits'],
            'total_spent': client['total_spent'] or 0,
            'last_visit': str(client['last_visit']) if client['last_visit'] else '',
            'preferred_barber': preferred['barber__display_name'] if preferred else '',
        })

    return Response(result)


@api_view(['GET'])
@permission_classes([IsAdminOrAbove])
def client_history_view(request, phone):
    """GET /api/admin/clients/{phone}/history/ — historial por teléfono."""
    bookings = (
        Booking.objects.filter(client_phone=phone)
        .select_related('barber', 'service')
        .order_by('-date', '-time')
    )

    history = []
    for b in bookings:
        history.append({
            'id': b.id,
            'date': str(b.date),
            'time': b.time.strftime('%H:%M'),
            'service': b.service.name if b.service else '',
            'barber': b.barber.display_name if b.barber else '',
            'price': b.price,
            'status': b.status,
        })

    # Client summary
    client_name = bookings.first().client_name if bookings.exists() else ''
    client_email = bookings.first().client_email if bookings.exists() else ''

    return Response({
        'name': client_name,
        'phone': phone,
        'email': client_email,
        'total_visits': len(history),
        'history': history,
    })
