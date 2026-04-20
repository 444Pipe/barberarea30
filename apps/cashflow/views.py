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


@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def daily_close_view(request):
    """
    POST /api/admin/cashflow/daily-close/
    Genera el cierre de caja del día actual. Agrupa ventas no cerradas.
    """
    from apps.cashflow.models import DailyClose, Expense
    from django.db.models import Sum

    today = timezone.localtime(timezone.now()).date()
    
    # Solo un cierre por día
    if DailyClose.objects.filter(date=today).exists():
        return Response({'error': 'El cierre de caja para el día de hoy ya fue generado.'}, status=status.HTTP_400_BAD_REQUEST)

    # Buscar ventas que no estén en un cierre
    pending_sales = Sale.objects.filter(included_in_daily_close__isnull=True)
    if not pending_sales.exists():
        return Response({'error': 'No hay ventas pendientes por cerrar.'}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        total_sales = pending_sales.aggregate(total=Sum('base_price'))['total'] or 0
        total_tips = pending_sales.aggregate(total=Sum('tip_amount'))['total'] or 0
        
        # Comisiones
        commissions = Commission.objects.filter(sale__in=pending_sales)
        total_commissions = commissions.aggregate(total=Sum('commission_amount'))['total'] or 0

        # Egresos variables del día (no asignados a un cierre)
        pending_expenses = Expense.objects.filter(included_in_daily_close__isnull=True)
        total_expenses = pending_expenses.aggregate(total=Sum('amount'))['total'] or 0

        # Ingreso neto: (Ventas Base) - (Comisiones) - (Descuentos asimilados por la empresa?) 
        # Actually total_sales was based on base_price. The real income for the company from sales is the final_price.
        total_final_prices = pending_sales.aggregate(total=Sum('final_price'))['total'] or 0
        net_income = total_final_prices - total_commissions - total_expenses

        daily_close = DailyClose.objects.create(
            date=today,
            closed_by=request.user,
            total_sales=total_final_prices,
            total_tips=total_tips,
            total_commissions=total_commissions,
            total_expenses=total_expenses,
            net_income=net_income
        )

        # Update sales and expenses
        pending_sales.update(included_in_daily_close=daily_close)
        pending_expenses.update(included_in_daily_close=daily_close)

        # Audit log
        log_audit(
            user=request.user,
            action='daily_close',
            obj=daily_close,
            changes={},
            request=request,
            extra_data={'msg': f"Realizó el Cierre de Caja del {today} con Neto ${net_income:,.0f}"}
        )

    return Response({
        'message': 'Cierre de caja exitoso',
        'close_id': daily_close.id,
        'net_income': daily_close.net_income
    })


@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def add_expense_view(request):
    """POST /api/admin/cashflow/expenses/ - Registrar un egreso."""
    from apps.cashflow.models import Expense
    data = request.data
    
    description = data.get('description', '').strip()
    amount = data.get('amount')
    expense_type = data.get('expense_type', 'variable')
    notes = data.get('notes', '')

    if not description or not amount:
        return Response({'error': 'Descripción y monto son obligatorios.'}, status=400)

    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except ValueError:
        return Response({'error': 'Monto inválido.'}, status=400)

    # Solo superadmin puede registrar fijos/inventario si queremos ser estrictos,
    # pero por ahora lo dejamos a nivel de IsOperationalAdminOrAbove y validamos rol:
    profile = getattr(request.user, 'profile', None)
    if profile and profile.role == 'operational_admin' and expense_type != 'variable':
        return Response({'error': 'Solo los administradores principales pueden registrar egresos fijos o de inventario.'}, status=403)

    expense = Expense.objects.create(
        description=description,
        amount=amount,
        expense_type=expense_type,
        notes=notes,
        registered_by=request.user
    )

    log_audit(
        user=request.user,
        action='payment',
        obj=expense,
        changes={'amount': str(amount), 'type': expense_type},
        request=request,
        extra_data={'msg': f"Registró un egreso de ${amount:,.0f}: {description}"}
    )

    return Response({'ok': True, 'expense_id': expense.id, 'message': 'Egreso registrado correctamente.'})
