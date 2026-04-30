from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from apps.users.permissions import IsOperationalAdminOrAbove, IsBarberOrAbove
from apps.bookings.models import Booking
from apps.cashflow.models import PaymentMethod
from apps.cashflow import services as cashflow_services
from apps.analytics.models import log_audit

from decimal import Decimal, InvalidOperation

def _safe_decimal(val, default=0):
    try:
        return Decimal(str(val)) if val else Decimal(default)
    except (ValueError, TypeError, InvalidOperation):
        return Decimal(default)

@api_view(['POST'])
@permission_classes([IsBarberOrAbove])
def checkout_booking_view(request, booking_id):
    """
    POST /api/admin/checkout/<booking_id>/
    Delegación a cashflow.services.process_checkout (atomic: Sale + Commission + Inventario + AuditLog).
    """
    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        return Response({'error': 'Reserva no encontrada'}, status=status.HTTP_404_NOT_FOUND)

    data = request.data
    try:
        sale = cashflow_services.process_checkout(
            booking=booking,
            confirmed_by=request.user,
            payment_method_id=data.get('payment_method_id'),
            payment_reference=data.get('payment_reference', ''),
            tip_amount=_safe_decimal(data.get('tip_amount'), 0),
            discount_amount=_safe_decimal(data.get('discount_amount'), 0),
            discount_assumed_by=data.get('discount_assumed_by', 'none'),
            commission_percentage=_safe_decimal(data.get('commission_percentage'), 50),
            notes=data.get('notes', ''),
            request=request,
        )
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({'error': f'Error interno al procesar el checkout: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    try:
        from apps.bookings.emails import send_post_sale_survey_email
        send_post_sale_survey_email(booking)
    except Exception as e:
        print("Error sending post sale survey email:", e)

    return Response({
        'message': 'Checkout completado correctamente',
        'sale_id': sale.id,
        'final_price': sale.final_price,
        'total_paid': sale.total_paid,
    })




@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def daily_close_view(request):
    """
    POST /api/admin/cashflow/daily-close/
    Genera el cierre de caja del día actual. Agrupa ventas no cerradas.
    """
    from apps.cashflow.models import DailyClose, Expense, Sale, Commission
    from django.db.models import Sum
    from django.db import transaction
    from django.utils import timezone

    today = timezone.localtime(timezone.now()).date()
    
    # Solo un cierre por día
    if DailyClose.objects.filter(date=today).exists():
        return Response({'error': 'El cierre de caja para el día de hoy ya fue generado.'}, status=status.HTTP_400_BAD_REQUEST)

    # Buscar ventas que no estén en un cierre
    pending_sales = Sale.objects.filter(included_in_daily_close__isnull=True)
    if not pending_sales.exists():
        return Response({'error': 'No hay ventas pendientes por cerrar.'}, status=status.HTTP_400_BAD_REQUEST)

    # Validar si hay ventas esperando aprobación (pending)
    unapproved_sales = pending_sales.filter(approval_status=Sale.STATUS_PENDING)
    if unapproved_sales.exists():
        return Response({'error': 'Hay ventas pendientes de aprobación. Por favor apruébelas o rechácelas antes de cerrar la caja.'}, status=status.HTTP_400_BAD_REQUEST)

    # Solo considerar las aprobadas
    pending_sales = pending_sales.filter(approval_status=Sale.STATUS_APPROVED)

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
        'net_income': daily_close.net_income,
        'debug': {
            'total_final_prices': float(total_final_prices),
            'total_commissions': float(total_commissions),
            'total_expenses': float(total_expenses),
            'total_tips': float(total_tips),
            'ventas_ids': list(pending_sales.values_list('id', flat=True)),
            'egresos_ids': list(pending_expenses.values_list('id', flat=True)),
        }
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
    image = request.FILES.get('image') if hasattr(request, 'FILES') else None

    # Validaciones
    if not description or not amount:
        return Response({'error': 'Descripción y monto son obligatorios.'}, status=400)

    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except Exception as e:
        return Response({'error': f'Monto inválido: {str(e)}'}, status=400)

    profile = getattr(request.user, 'profile', None)
    if profile and profile.role == 'operational_admin' and expense_type != 'variable':
        return Response({'error': 'Solo los administradores principales pueden registrar egresos fijos o de inventario.'}, status=403)

    try:
        expense = Expense.objects.create(
            description=description,
            amount=amount,
            expense_type=expense_type,
            notes=notes,
            registered_by=request.user,
            image=image
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
    except Exception as e:
        return Response({'error': f'Error inesperado al guardar: {str(e)}'}, status=500)


# ─── SISTEMA DE APROBACIÓN DE VENTAS ──────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsOperationalAdminOrAbove])
def pending_approvals_view(request):
    """GET /api/admin/cashflow/pending-approvals/"""
    from apps.cashflow.models import Sale
    sales = Sale.objects.select_related('barber', 'service', 'booking').filter(
        approval_status=Sale.STATUS_PENDING,
        included_in_daily_close__isnull=True
    ).order_by('-created_at')

    data = []
    for s in sales:
        data.append({
            'id': s.id,
            'barber_name': s.barber.display_name if s.barber else 'N/A',
            'service_name': s.service.name if s.service else 'General',
            'client_name': s.booking.client_name if s.booking else 'N/A',
            'final_price': float(s.final_price),
            'tip_amount': float(s.tip_amount),
            'total_paid': float(s.total_paid),
            'created_at': s.created_at.strftime('%Y-%m-%d %H:%M'),
        })
    return Response({'pending_approvals': data})


@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def approve_sale_view(request, sale_id):
    """POST /api/admin/cashflow/approvals/<sale_id>/approve/"""
    from apps.cashflow.models import Sale
    from django.utils import timezone
    try:
        sale = Sale.objects.get(id=sale_id, approval_status=Sale.STATUS_PENDING)
    except Sale.DoesNotExist:
        return Response({'error': 'Venta no encontrada o ya procesada.'}, status=404)

    sale.approval_status = Sale.STATUS_APPROVED
    sale.approved_by = request.user
    sale.approved_at = timezone.now()
    sale.save(update_fields=['approval_status', 'approved_by', 'approved_at'])

    log_audit(
        user=request.user,
        action='update',
        obj=sale,
        changes={'approval_status': 'approved'},
        request=request,
        extra_data={'msg': f"Aprobó la venta #{sale.id} del barbero {sale.barber.display_name if sale.barber else 'N/A'}"}
    )

    return Response({'ok': True, 'message': 'Venta aprobada.'})


@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def reject_sale_view(request, sale_id):
    """POST /api/admin/cashflow/approvals/<sale_id>/reject/"""
    from apps.cashflow.models import Sale
    from django.utils import timezone
    from django.db import transaction

    reason = request.data.get('reason', 'Sin razón especificada.')

    try:
        sale = Sale.objects.get(id=sale_id, approval_status=Sale.STATUS_PENDING)
    except Sale.DoesNotExist:
        return Response({'error': 'Venta no encontrada o ya procesada.'}, status=404)

    with transaction.atomic():
        booking = sale.booking
        barber_name = sale.barber.display_name if sale.barber else 'N/A'

        # Restaurar estado del booking a pendiente
        if booking:
            booking.status = 'pending'
            booking.completed_at = None
            booking.save(update_fields=['status', 'completed_at'])

        # Eliminar la venta (que por cascada elimina la comisión)
        sale_id_num = sale.id
        sale.delete()

        log_audit(
            user=request.user,
            action='delete',
            obj=None,
            changes={},
            request=request,
            extra_data={'msg': f"Rechazó y eliminó la venta #{sale_id_num} del barbero {barber_name}. Razón: {reason}"}
        )

    return Response({'ok': True, 'message': 'Venta rechazada y eliminada. La reserva vuelve a estar Pendiente.'})
