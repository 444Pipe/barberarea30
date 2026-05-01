from django.utils import timezone as tz
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from apps.users.permissions import IsOperationalAdminOrAbove, IsBarberOrAbove, IsSuperAdmin
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
            added_value_amount=_safe_decimal(data.get('added_value_amount'), 0),
            added_value_description=data.get('added_value_description', ''),
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
    from apps.cashflow.models import DailyClose, Expense, Sale, Commission, InventorySale
    from django.db.models import Sum
    from django.db import transaction
    from django.utils import timezone

    today = timezone.localtime(timezone.now()).date()
    
    # Solo un cierre por día
    if DailyClose.objects.filter(date=today).exists():
        return Response({'error': 'El cierre de caja para el día de hoy ya fue generado.'}, status=status.HTTP_400_BAD_REQUEST)

    # Buscar ventas que no estén en un cierre
    pending_sales = Sale.objects.filter(included_in_daily_close__isnull=True)
    pending_inventory_sales = InventorySale.objects.filter(included_in_daily_close__isnull=True)
    
    if not pending_sales.exists() and not pending_inventory_sales.exists():
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
        
        # Ventas de inventario
        total_inventory_sales = pending_inventory_sales.aggregate(total=Sum('total_price'))['total'] or 0
        
        # Comisiones
        commissions = Commission.objects.filter(sale__in=pending_sales)
        total_commissions = commissions.aggregate(total=Sum('commission_amount'))['total'] or 0

        # Egresos variables del día (no asignados a un cierre)
        pending_expenses = Expense.objects.filter(included_in_daily_close__isnull=True)
        total_expenses = pending_expenses.aggregate(total=Sum('amount'))['total'] or 0

        # Ingreso neto: (Ventas Base) - (Comisiones) - (Descuentos asimilados por la empresa?) 
        # Actually total_sales was based on base_price. The real income for the company from sales is the final_price.
        total_final_prices = pending_sales.aggregate(total=Sum('final_price'))['total'] or 0
        net_income = total_final_prices + total_inventory_sales - total_commissions - total_expenses

        daily_close = DailyClose.objects.create(
            date=today,
            closed_by=request.user,
            total_sales=total_final_prices,
            total_inventory_sales=total_inventory_sales,
            total_tips=total_tips,
            total_commissions=total_commissions,
            total_expenses=total_expenses,
            net_income=net_income
        )

        # Update sales and expenses
        pending_sales.update(included_in_daily_close=daily_close)
        pending_inventory_sales.update(included_in_daily_close=daily_close)
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
            'total_inventory_sales': float(total_inventory_sales),
            'total_commissions': float(total_commissions),
            'total_expenses': float(total_expenses),
            'total_tips': float(total_tips),
            'ventas_ids': list(pending_sales.values_list('id', flat=True)),
            'inventory_sales_ids': list(pending_inventory_sales.values_list('id', flat=True)),
            'egresos_ids': list(pending_expenses.values_list('id', flat=True)),
        }
    })

@api_view(['GET'])
@permission_classes([IsOperationalAdminOrAbove])
def daily_close_detail_view(request, close_id):
    """GET /api/admin/cashflow/daily-close/<id>/detail/ - Detalles de un cierre de caja."""
    from apps.cashflow.models import DailyClose, Sale, Commission, Expense, InventorySale
    from django.db.models import Sum

    try:
        daily_close = DailyClose.objects.get(pk=close_id)
    except DailyClose.DoesNotExist:
        return Response({'error': 'Cierre no encontrado'}, status=404)

    # Ventas asociadas a este cierre
    sales = daily_close.sales.all().select_related('barber', 'service', 'commission', 'booking', 'payment_method', 'approved_by')
    inventory_sales = daily_close.inventory_sales.all().select_related('item', 'payment_method', 'sold_by')
    expenses = daily_close.expenses.all()

    from django.utils import timezone
    # Desglose por barbero
    barbers_data = {}
    sales_detail = []
    for sale in sales:
        barber_id = sale.barber.id if sale.barber else 'unassigned'
        barber_name = sale.barber.display_name if sale.barber else 'Sin Barbero'
        
        if barber_id not in barbers_data:
            barbers_data[barber_id] = {
                'name': barber_name,
                'sales_count': 0,
                'total_sales': 0,
                'total_tips': 0,
                'total_commissions': 0,
            }
        
        b_data = barbers_data[barber_id]
        b_data['sales_count'] += 1
        b_data['total_sales'] += float(sale.final_price)
        b_data['total_tips'] += float(sale.tip_amount)
        
        if hasattr(sale, 'commission'):
            b_data['total_commissions'] += float(sale.commission.commission_amount)

        sales_detail.append({
            'type': 'service',
            'client_name': sale.booking.client_name if sale.booking else 'N/A',
            'service_name': sale.service.name if sale.service else 'General',
            'time': timezone.localtime(sale.created_at).strftime('%I:%M %p'),
            'base_price': float(sale.base_price),
            'final_price': float(sale.final_price),
            'tip_amount': float(sale.tip_amount),
            'payment_method': sale.payment_method.name if sale.payment_method else 'N/A',
            'barber_name': barber_name,
            'approved_by': sale.approved_by.username if sale.approved_by else 'N/A'
        })
        
    for inv_sale in inventory_sales:
        i_price = float(inv_sale.total_price)
        sales_detail.append({
            'type': 'inventory',
            'client_name': 'Cliente Local',
            'service_name': f"{inv_sale.quantity}x {inv_sale.item.name}" if inv_sale.item else 'Producto',
            'time': timezone.localtime(inv_sale.created_at).strftime('%I:%M %p'),
            'base_price': i_price,
            'final_price': i_price,
            'tip_amount': 0,
            'payment_method': inv_sale.payment_method.name if inv_sale.payment_method else 'N/A',
            'barber_name': 'N/A',
            'approved_by': inv_sale.sold_by.username if inv_sale.sold_by else 'N/A'
        })

    # Detalle de egresos
    expenses_data = []
    for exp in expenses:
        expenses_data.append({
            'description': exp.description,
            'amount': float(exp.amount),
            'type': exp.get_expense_type_display() if hasattr(exp, 'get_expense_type_display') else exp.expense_type
        })

    return Response({
        'id': daily_close.id,
        'date': daily_close.date.strftime('%Y-%m-%d'),
        'closed_at': daily_close.closed_at.strftime('%Y-%m-%d %H:%M:%S'),
        'closed_by': daily_close.closed_by.username,
        'total_sales': float(daily_close.total_sales),
        'total_inventory_sales': float(daily_close.total_inventory_sales),
        'total_tips': float(daily_close.total_tips),
        'total_commissions': float(daily_close.total_commissions),
        'total_expenses': float(daily_close.total_expenses),
        'net_income': float(daily_close.net_income),
        'barbers': list(barbers_data.values()),
        'expenses': expenses_data,
        'sales_detail': sorted(sales_detail, key=lambda x: x['time'], reverse=True),
    })



@api_view(['DELETE'])
@permission_classes([IsSuperAdmin])
def delete_daily_close_view(request, close_id):
    """DELETE /api/admin/cashflow/daily-close/<id>/delete/ - Eliminar cierre de caja (solo superadmin)."""
    from apps.cashflow.models import DailyClose
    try:
        daily_close = DailyClose.objects.get(pk=close_id)
        date_str = daily_close.date.strftime('%Y-%m-%d')
        
        # Desvincular ventas y egresos
        daily_close.sales.update(included_in_daily_close=None)
        daily_close.inventory_sales.update(included_in_daily_close=None)
        daily_close.expenses.update(included_in_daily_close=None)
        
        daily_close.delete()
        
        log_audit(
            user=request.user,
            action='delete',
            obj=None,
            changes={},
            request=request,
            extra_data={'msg': f"Eliminó el Cierre de Caja del {date_str}"}
        )
        return Response({'ok': True, 'message': 'Cierre de caja eliminado correctamente.'})
    except DailyClose.DoesNotExist:
        return Response({'error': 'Cierre no encontrado.'}, status=404)
    except Exception as e:
        return Response({'error': f'Error al eliminar: {str(e)}'}, status=500)


@api_view(['GET'])
@permission_classes([IsOperationalAdminOrAbove])
def live_cashflow_detail_view(request):
    """GET /api/admin/cashflow/live-detail/ - Detalles en vivo del día actual (antes del cierre)."""
    from apps.cashflow.models import Sale, Expense, Commission, InventorySale
    from django.db.models import Sum
    from django.utils import timezone

    today = timezone.localtime(timezone.now()).date()

    # Ventas aprobadas pendientes de cierre
    approved_sales = Sale.objects.filter(
        approval_status=Sale.STATUS_APPROVED, 
        included_in_daily_close__isnull=True
    ).select_related('barber', 'service', 'commission', 'booking', 'payment_method', 'approved_by')
    
    # Ventas de inventario
    inventory_sales = InventorySale.objects.filter(included_in_daily_close__isnull=True).select_related('item', 'payment_method', 'sold_by')

    # Ventas pendientes de aprobación
    pending_approvals_count = Sale.objects.filter(
        approval_status=Sale.STATUS_PENDING, 
        included_in_daily_close__isnull=True
    ).count()

    expenses = Expense.objects.filter(included_in_daily_close__isnull=True)

    barbers_data = {}
    sales_detail = []
    
    total_sales_overall = 0
    total_tips_overall = 0
    total_commissions_overall = 0

    for sale in approved_sales:
        barber_id = sale.barber.id if sale.barber else 'unassigned'
        barber_name = sale.barber.display_name if sale.barber else 'Sin Barbero'
        
        if barber_id not in barbers_data:
            barbers_data[barber_id] = {
                'name': barber_name,
                'sales_count': 0,
                'total_sales': 0,
                'total_tips': 0,
                'total_commissions': 0,
            }
        
        b_data = barbers_data[barber_id]
        b_data['sales_count'] += 1
        
        f_price = float(sale.final_price)
        t_tip = float(sale.tip_amount)
        c_amount = float(sale.commission.commission_amount) if hasattr(sale, 'commission') else 0
        
        b_data['total_sales'] += f_price
        b_data['total_tips'] += t_tip
        b_data['total_commissions'] += c_amount
        
        total_sales_overall += f_price
        total_tips_overall += t_tip
        total_commissions_overall += c_amount

        sales_detail.append({
            'type': 'service',
            'client_name': sale.booking.client_name if sale.booking else 'N/A',
            'service_name': sale.service.name if sale.service else 'General',
            'time': timezone.localtime(sale.created_at).strftime('%I:%M %p'),
            'base_price': float(sale.base_price),
            'final_price': f_price,
            'tip_amount': t_tip,
            'payment_method': sale.payment_method.name if sale.payment_method else 'N/A',
            'barber_name': barber_name,
            'approved_by': sale.approved_by.username if sale.approved_by else 'N/A'
        })

    # Add inventory sales
    total_inventory_sales_overall = 0
    for inv_sale in inventory_sales:
        i_price = float(inv_sale.total_price)
        total_inventory_sales_overall += i_price
        sales_detail.append({
            'type': 'inventory',
            'client_name': 'Cliente Local',
            'service_name': f"{inv_sale.quantity}x {inv_sale.item.name}" if inv_sale.item else 'Producto',
            'time': timezone.localtime(inv_sale.created_at).strftime('%I:%M %p'),
            'base_price': i_price,
            'final_price': i_price,
            'tip_amount': 0,
            'payment_method': inv_sale.payment_method.name if inv_sale.payment_method else 'N/A',
            'barber_name': 'N/A',
            'approved_by': inv_sale.sold_by.username if inv_sale.sold_by else 'N/A'
        })

    expenses_data = []
    total_expenses_overall = 0
    for exp in expenses:
        amt = float(exp.amount)
        total_expenses_overall += amt
        expenses_data.append({
            'description': exp.description,
            'amount': amt,
            'type': exp.get_expense_type_display() if hasattr(exp, 'get_expense_type_display') else exp.expense_type
        })

    net_income = total_sales_overall + total_inventory_sales_overall - total_commissions_overall - total_expenses_overall

    return Response({
        'date': today.strftime('%Y-%m-%d'),
        'total_sales': total_sales_overall,
        'total_inventory_sales': total_inventory_sales_overall,
        'total_tips': total_tips_overall,
        'total_commissions': total_commissions_overall,
        'total_expenses': total_expenses_overall,
        'net_income': net_income,
        'pending_approvals_count': pending_approvals_count,
        'barbers': list(barbers_data.values()),
        'expenses': expenses_data,
        'sales_detail': sorted(sales_detail, key=lambda x: x['time'], reverse=True),
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


@api_view(['DELETE'])
@permission_classes([IsSuperAdmin])
def delete_expense_view(request, expense_id):
    """DELETE /api/admin/cashflow/expenses/<id>/ - Eliminar un egreso (solo superadmin)."""
    from apps.cashflow.models import Expense
    try:
        expense = Expense.objects.get(pk=expense_id)
        description = expense.description
        amount = float(expense.amount)
        log_audit(
            user=request.user,
            action='delete',
            obj=expense,
            changes={},
            request=request,
            extra_data={'msg': f"Eliminó el egreso '${amount:,.0f} - {description}'"}
        )
        expense.delete()
        return Response({'ok': True, 'message': 'Egreso eliminado correctamente.'})
    except Expense.DoesNotExist:
        return Response({'error': 'Egreso no encontrado.'}, status=404)
    except Exception as e:
        return Response({'error': f'Error al eliminar: {str(e)}'}, status=500)


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
            'created_at': tz.localtime(s.created_at).strftime('%d/%m/%Y %I:%M %p'),
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


# ─── VENTA DIRECTA DE INVENTARIO ──────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def create_inventory_sale_view(request):
    """POST /api/admin/cashflow/inventory-sales/ - Vender bebida u otro insumo."""
    from apps.cashflow.models import InventorySale, PaymentMethod
    from apps.inventory.models import InventoryItem, InventoryMovement
    from django.db import transaction

    data = request.data
    item_id = data.get('item_id')
    quantity = data.get('quantity', 1)
    payment_method_id = data.get('payment_method_id')

    try:
        quantity = float(quantity)
        if quantity <= 0:
            return Response({'error': 'La cantidad debe ser mayor a 0'}, status=400)
    except ValueError:
        return Response({'error': 'Cantidad inválida'}, status=400)

    try:
        item = InventoryItem.objects.get(pk=item_id)
    except InventoryItem.DoesNotExist:
        return Response({'error': 'Producto no encontrado'}, status=404)

    payment_method = None
    if payment_method_id:
        payment_method = PaymentMethod.objects.filter(id=payment_method_id).first()

    with transaction.atomic():
        # Restar del inventario
        from decimal import Decimal
        qty_before = item.quantity
        item.quantity -= Decimal(str(quantity))
        if item.quantity < 0:
            item.quantity = 0
        item.save()

        # Registrar movimiento
        InventoryMovement.objects.create(
            item=item,
            movement_type='out',
            quantity=quantity,
            quantity_before=qty_before,
            quantity_after=item.quantity,
            performed_by=request.user,
            notes='Venta directa de mostrador'
        )

        # Crear venta
        sale = InventorySale.objects.create(
            item=item,
            quantity=quantity,
            unit_price=item.sale_price,
            payment_method=payment_method,
            sold_by=request.user
        )

        log_audit(
            user=request.user,
            action='payment',
            obj=sale,
            changes={'total_price': str(sale.total_price)},
            request=request,
            extra_data={'msg': f"Vendió {quantity}x {item.name} por ${sale.total_price:,.0f}"}
        )

    return Response({
        'ok': True, 
        'sale_id': sale.id, 
        'message': f'Venta registrada correctamente: ${sale.total_price:,.0f}'
    }, status=201)
