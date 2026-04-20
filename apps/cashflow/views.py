from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.utils import timezone

from apps.users.permissions import IsOperationalAdminOrAbove
from apps.bookings.models import Booking
from apps.cashflow.models import Sale, PaymentMethod, Commission
from apps.inventory.models import InventoryItem, ServiceInventoryItem, InventoryMovement
from apps.analytics.models import log_audit

@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def checkout_booking_view(request, booking_id):
    """
    POST /api/admin/checkout/<booking_id>/
    Crea la venta, liquida la comisión y descuenta el inventario.
    """
    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        return Response({'error': 'Reserva no encontrada'}, status=status.HTTP_404_NOT_FOUND)

    if booking.status in ['completed', 'cancelled']:
        return Response({'error': f'La reserva ya está {booking.status}'}, status=status.HTTP_400_BAD_REQUEST)

    # Datos del checkout
    data = request.data
    payment_method_id = data.get('payment_method_id')
    payment_reference = data.get('payment_reference', '')
    tip_amount = float(data.get('tip_amount', 0))
    discount_amount = float(data.get('discount_amount', 0))
    discount_assumed_by = data.get('discount_assumed_by', 'none') # 'company', 'barber', 'none'
    notes = data.get('notes', '')

    with transaction.atomic():
        # 1. Crear Venta
        payment_method = PaymentMethod.objects.filter(id=payment_method_id).first() if payment_method_id else None
        
        sale = Sale.objects.create(
            booking=booking,
            barber=booking.barber,
            service=booking.service,
            base_price=booking.price,
            discount_amount=discount_amount,
            discount_assumed_by=discount_assumed_by,
            tip_amount=tip_amount,
            payment_method=payment_method,
            payment_reference=payment_reference,
            confirmed_by=request.user,
            notes=notes
        )

        # 2. Crear Comisión (si hay barbero)
        if booking.barber:
            Commission.objects.create(
                sale=sale,
                barber=booking.barber,
                percentage=50.00 # TODO: Leer del perfil del barbero si existe campo custom
            )

        # 3. Descontar Inventario
        if booking.service:
            # Requerimientos explícitos
            requirements = ServiceInventoryItem.objects.filter(service=booking.service)
            for req in requirements:
                item = req.item
                qty_before = item.quantity
                item.quantity -= req.quantity_per_service
                item.save()
                
                InventoryMovement.objects.create(
                    item=item,
                    movement_type='out',
                    quantity=req.quantity_per_service,
                    quantity_before=qty_before,
                    quantity_after=item.quantity,
                    booking=booking,
                    performed_by=request.user,
                    notes=f"Consumo por servicio {booking.service.name}"
                )

        # 4. Actualizar Reserva
        booking.status = 'completed'
        booking.completed_at = timezone.now()
        booking.save()

        # 5. Registro de Auditoría
        log_audit(
            user=request.user,
            action='payment',
            obj=sale,
            changes={
                'total_paid': str(sale.total_paid),
                'payment_method': payment_method.name if payment_method else 'Desconocido',
                'tip': str(tip_amount),
                'discount': str(discount_amount)
            },
            request=request,
            extra_data={'msg': f"Completó la reserva de {booking.client_name} por ${sale.total_paid:,.0f}"}
        )

    return Response({
        'message': 'Checkout completado correctamente',
        'sale_id': sale.id,
        'final_price': sale.final_price,
        'total_paid': sale.total_paid
    })
