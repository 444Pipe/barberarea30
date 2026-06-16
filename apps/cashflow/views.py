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

    # Tomar la comisión configurada en el perfil del barbero. Si no hay barbero
    # o el valor no es válido, caer a un default razonable (40% / 50% Frank).
    barber_name = booking.barber.display_name.lower() if booking.barber else ''
    if booking.barber and booking.barber.commission_percentage is not None:
        comm_percentage = booking.barber.commission_percentage
    else:
        comm_percentage = 50 if 'frank' in barber_name else 40

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
            commission_percentage=comm_percentage,
            notes=data.get('notes', ''),
            frank_materials_cost=_safe_decimal(data.get('frank_materials_cost'), 0),
            frank_labor_cost=_safe_decimal(data.get('frank_labor_cost'), 0),
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
        
        # Separar a Franko
        frank_commissions = commissions.filter(barber__display_name__icontains='frank')
        frank_total_comm = frank_commissions.aggregate(total=Sum('commission_amount'))['total'] or 0
        frank_total_tips = frank_commissions.aggregate(total=Sum('tip_amount'))['total'] or 0
        frank_pay = frank_total_comm + frank_total_tips
        
        # Comisiones de los demás (40%)
        other_commissions = commissions.exclude(barber__display_name__icontains='frank')
        total_commissions = other_commissions.aggregate(total=Sum('commission_amount'))['total'] or 0

        if frank_pay > 0:
            # Crear Egreso Diario para Franko
            frank_expense = Expense.objects.create(
                description="Pago Diario: Franko",
                amount=frank_pay,
                expense_type='variable',
                registered_by=request.user
            )
            # Marcar automáticamente como pagado
            frank_commissions.update(is_paid=True, is_paid_in_daily_close=True, paid_at=timezone.now())

        # Egresos variables del día (no asignados a un cierre).
        # OJO: este total INCLUYE el "Pago Diario: Franko" recién creado, que
        # a su vez es (comisión + propinas). Las propinas del cliente son
        # pass-through (cliente → barbero), no son revenue ni gasto real de
        # la empresa, así que las restamos del total para que el net no
        # quede artificialmente más bajo.
        pending_expenses = Expense.objects.filter(included_in_daily_close__isnull=True)
        total_expenses = pending_expenses.aggregate(total=Sum('amount'))['total'] or 0
        expenses_for_net = total_expenses - frank_total_tips

        # Ingreso neto: revenue de servicios + inventario - comisiones de los
        # demás barberos (no Frank — su comisión ya está en Expense) - egresos
        # reales (excluyendo el componente de propina del pago a Frank).
        total_final_prices = pending_sales.aggregate(total=Sum('final_price'))['total'] or 0
        net_income = total_final_prices + total_inventory_sales - total_commissions - expenses_for_net

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
    payment_methods_data = {}
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
        
        pm_name = sale.payment_method.name if sale.payment_method else 'Efectivo/Sin Especificar'
        payment_methods_data[pm_name] = payment_methods_data.get(pm_name, 0) + float(sale.final_price)
        
        if hasattr(sale, 'commission'):
            b_data['total_commissions'] += float(sale.commission.commission_amount)

        sales_detail.append({
            'type': 'service',
            'id': sale.id,
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
        
        pm_name = inv_sale.payment_method.name if inv_sale.payment_method else 'Efectivo/Sin Especificar'
        payment_methods_data[pm_name] = payment_methods_data.get(pm_name, 0) + i_price
        
        sales_detail.append({
            'type': 'inventory',
            'id': inv_sale.id,
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
        'payment_methods': payment_methods_data,
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
    payment_methods_data = {}

    total_sales_overall = 0
    total_tips_overall = 0
    total_commissions_overall = 0
    frank_pay_live = 0
    # Componente "propina" del pago a Frank — pass-through (cliente→barbero),
    # no es gasto real de la empresa. Se trackea para corregir el net_income.
    frank_tips_live = 0

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

        if 'frank' in barber_name.lower():
            frank_pay_live += c_amount + t_tip
            frank_tips_live += t_tip
        else:
            total_commissions_overall += c_amount

        pm_name = sale.payment_method.name if sale.payment_method else 'Efectivo/Sin Especificar'
        payment_methods_data[pm_name] = payment_methods_data.get(pm_name, 0) + f_price

        commission_pct = None
        if hasattr(sale, 'commission') and sale.commission:
            commission_pct = float(sale.commission.percentage)
        sales_detail.append({
            'type': 'service',
            'id': sale.id,
            'client_name': sale.booking.client_name if sale.booking else 'N/A',
            'service_name': sale.service.name if sale.service else 'General',
            'time': timezone.localtime(sale.created_at).strftime('%I:%M %p'),
            'base_price': float(sale.base_price),
            'discount_amount': float(sale.discount_amount),
            'discount_assumed_by': sale.discount_assumed_by,
            'final_price': f_price,
            'tip_amount': t_tip,
            'commission_amount': c_amount,
            'commission_percentage': commission_pct,
            'payment_method': sale.payment_method.name if sale.payment_method else 'N/A',
            'barber_name': barber_name,
            'approved_by': sale.approved_by.username if sale.approved_by else 'N/A'
        })

    # Add inventory sales
    total_inventory_sales_overall = 0
    for inv_sale in inventory_sales:
        i_price = float(inv_sale.total_price)
        total_inventory_sales_overall += i_price
        
        pm_name = inv_sale.payment_method.name if inv_sale.payment_method else 'Efectivo/Sin Especificar'
        payment_methods_data[pm_name] = payment_methods_data.get(pm_name, 0) + i_price
        
        sales_detail.append({
            'type': 'inventory',
            'id': inv_sale.id,
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
        
    if frank_pay_live > 0:
        expenses_data.append({
            'description': 'Pago Diario: Franko (Comisiones + Propinas)',
            'amount': frank_pay_live,
            'type': 'Variable'
        })
        total_expenses_overall += frank_pay_live

    # Restar el componente de propina de los gastos al calcular net_income:
    # la propina entró como cash y sale como cash (pass-through), no afecta
    # la utilidad real de la empresa.
    expenses_for_net = total_expenses_overall - frank_tips_live
    net_income = total_sales_overall + total_inventory_sales_overall - total_commissions_overall - expenses_for_net

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
        'payment_methods': payment_methods_data,
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
            booking.price = sale.base_price
            booking.save(update_fields=['status', 'completed_at', 'price'])

        # Devolver al inventario lo que process_checkout descontó por esta
        # reserva. Si no revertimos, el stock queda permanentemente bajo aunque
        # la venta fue rechazada — y los pedidos a proveedor salen torcidos.
        if booking:
            from apps.inventory.models import InventoryMovement
            consumptions = InventoryMovement.objects.filter(
                booking=booking, movement_type='out'
            ).select_related('item')
            for mov in consumptions:
                item = mov.item
                if item is None:
                    continue
                qty_before = item.quantity
                item.quantity = qty_before + mov.quantity
                item.save(update_fields=['quantity'])
                InventoryMovement.objects.create(
                    item=item,
                    movement_type='adjustment',
                    quantity=mov.quantity,
                    quantity_before=qty_before,
                    quantity_after=item.quantity,
                    booking=booking,
                    performed_by=request.user,
                    notes=(
                        f'Reverso por rechazo de venta #{sale.id}: '
                        f'se devuelve {mov.quantity} {item.unit}.'
                    ),
                )

        # Si era un servicio manual de Frank, también se había generado un
        # Expense "Materiales Servicio: <cliente> (venta #<id>)" en
        # process_checkout. Lo eliminamos vía el sale_id en la descripción
        # — antes filtrábamos por description+created_at>=sale.created_at,
        # lo que podía borrar el egreso de OTRA venta del mismo cliente.
        if booking:
            from apps.cashflow.models import Expense
            Expense.objects.filter(
                description__endswith=f'(venta #{sale.id})',
                included_in_daily_close__isnull=True,
                expense_type='variable',
            ).delete()

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


@api_view(['GET'])
@permission_classes([IsOperationalAdminOrAbove])
def fix_frank_history_view(request):
    """GET /api/admin/cashflow/fix-frank-history/"""
    from apps.cashflow.models import Commission, DailyClose, Expense
    from apps.barbers.models import Barber
    from decimal import Decimal
    from django.db.models import Sum
    from django.utils import timezone
    from django.db import transaction

    frank = Barber.objects.filter(display_name__icontains='frank').first()
    if not frank:
        frank = Barber.objects.filter(user__first_name__icontains='frank').first()
        
    if not frank:
        return Response({'error': 'Frank no encontrado'}, status=404)

    # También actualizar el perfil de Franko para que futuras comisiones sean del 50% por defecto
    frank.commission_percentage = Decimal('50.00')
    frank.save(update_fields=['commission_percentage'])

    with transaction.atomic():
        # 1. Ajustar todas las comisiones de Franko al 50%
        frank_commissions = Commission.objects.filter(barber=frank)
        updated_comms = 0
        for comm in frank_commissions:
            # Bypass save() recalculation if manual service had materials
            # We just force percentage to 50% and do it directly via update
            new_pct = Decimal('50.00')
            new_comm_amt = (comm.basis_amount * new_pct) / Decimal('100.00')
            new_total = new_comm_amt + comm.tip_amount
            Commission.objects.filter(id=comm.id).update(
                percentage=new_pct,
                commission_amount=new_comm_amt,
                total_earnings=new_total
            )
            updated_comms += 1

        # 2. Corregir los Cierres Diarios
        closes = DailyClose.objects.all()
        updated_closes = 0
        
        for close in closes:
            sales = close.sales.all()
            comms = Commission.objects.filter(sale__in=sales)
            
            # Comisiones de Franko en este cierre
            frank_comms = comms.filter(barber=frank)
            frank_total_comm = frank_comms.aggregate(total=Sum('commission_amount'))['total'] or 0
            frank_total_tips = frank_comms.aggregate(total=Sum('tip_amount'))['total'] or 0
            frank_pay = frank_total_comm + frank_total_tips
            
            # Comisiones de los demás
            other_comms = comms.exclude(barber=frank)
            total_other_comms = other_comms.aggregate(total=Sum('commission_amount'))['total'] or 0
            
            # Buscar o crear el gasto de Franko
            expense = close.expenses.filter(description__icontains='Pago Diario: Franko').first()
            
            if frank_pay > 0:
                if expense:
                    Expense.objects.filter(id=expense.id).update(amount=frank_pay)
                else:
                    Expense.objects.create(
                        description='Pago Diario: Franko',
                        amount=frank_pay,
                        expense_type='variable',
                        registered_by=close.closed_by,
                        included_in_daily_close=close
                    )
                frank_comms.update(is_paid=True, is_paid_in_daily_close=True, paid_at=close.closed_at or timezone.now())
            elif expense:
                expense.delete()
            
            # Recalcular totales del cierre
            total_expenses = close.expenses.aggregate(total=Sum('amount'))['total'] or 0
            total_sales = sales.aggregate(total=Sum('final_price'))['total'] or 0
            total_tips = sales.aggregate(total=Sum('tip_amount'))['total'] or 0
            total_inventory = close.inventory_sales.aggregate(total=Sum('total_price'))['total'] or 0
            
            # Neto = (Ventas) + (Inventario) - (Comisiones de otros) - (Gastos, incluido Frank)
            net_income = total_sales + total_inventory - total_other_comms - total_expenses
            
            DailyClose.objects.filter(id=close.id).update(
                total_sales=total_sales,
                total_tips=total_tips,
                total_commissions=total_other_comms,
                total_expenses=total_expenses,
                net_income=net_income
            )
            updated_closes += 1

    return Response({
        'message': 'Historial corregido exitosamente.',
        'comisiones_actualizadas': updated_comms,
        'cierres_actualizados': updated_closes,
        'perfil_actualizado': True
    })

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
        from decimal import Decimal
        quantity = Decimal(str(quantity))
        if quantity <= 0:
            return Response({'error': 'La cantidad debe ser mayor a 0'}, status=400)
    except Exception:
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

# ─── GESTIÓN DE PAGOS A BARBEROS ──────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsOperationalAdminOrAbove])
def unpaid_commissions_view(request):
    """GET /api/admin/cashflow/barber-payments/ - Saldo pendiente por pagar a cada barbero.

    Acumulado = comisiones + propinas (de ventas aprobadas, no pagadas).
    A ese acumulado se le restan los vales/adelantos pendientes para obtener el
    neto realmente liquidable.
    """
    from apps.cashflow.models import Commission, BarberAdvance
    from apps.barbers.models import Barber
    from django.db.models import Sum
    from django.db.models.functions import TruncDate

    # Comisiones aprobadas y no pagadas, agrupadas por barbero.
    # Excluimos a Frank porque su pago se automatiza en el cierre diario.
    unpaid_commissions = Commission.objects.filter(
        is_paid=False,
        sale__approval_status='approved'
    ).exclude(
        barber__display_name__icontains='frank'
    ).values('barber_id').annotate(
        total_commissions=Sum('commission_amount'),
        total_tips=Sum('tip_amount'),
        total_earnings=Sum('total_earnings')
    )
    comm_by_barber = {c['barber_id']: c for c in unpaid_commissions}

    # Vales/adelantos pendientes de descontar, agrupados por barbero.
    unsettled_advances = BarberAdvance.objects.filter(
        is_settled=False
    ).exclude(
        barber__display_name__icontains='frank'
    ).values('barber_id').annotate(
        total_advances=Sum('amount')
    )
    adv_by_barber = {a['barber_id']: a for a in unsettled_advances}

    # Mostramos a cualquier barbero con comisiones pendientes O con vales pendientes.
    barber_ids = set(comm_by_barber) | set(adv_by_barber)
    barbers = Barber.objects.in_bulk(barber_ids)

    data = []
    for barber_id in barber_ids:
        barber = barbers.get(barber_id)
        if not barber:
            continue

        comm = comm_by_barber.get(barber_id, {})
        total_commissions = float(comm.get('total_commissions') or 0)
        total_tips = float(comm.get('total_tips') or 0)
        total_earnings = float(comm.get('total_earnings') or 0)
        total_advances = float(adv_by_barber.get(barber_id, {}).get('total_advances') or 0)
        net_payable = total_earnings - total_advances

        # Desglose diario de las ganancias (comisiones + propinas).
        daily_breakdown = Commission.objects.filter(
            barber_id=barber_id,
            is_paid=False,
            sale__approval_status='approved'
        ).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            daily_total=Sum('total_earnings'),
            daily_commissions=Sum('commission_amount'),
            daily_tips=Sum('tip_amount')
        ).order_by('-date')

        history = []
        for day in daily_breakdown:
            if day['date']:
                history.append({
                    'date': day['date'].strftime('%Y-%m-%d'),
                    'total': float(day['daily_total'] or 0),
                    'commissions': float(day['daily_commissions'] or 0),
                    'tips': float(day['daily_tips'] or 0)
                })

        # Vales/adelantos pendientes (el "historial de vales" que se descuenta).
        advances_qs = BarberAdvance.objects.filter(
            barber_id=barber_id, is_settled=False
        ).select_related('created_by').order_by('-created_at')
        advances = [{
            'id': adv.id,
            'amount': float(adv.amount),
            'reason': adv.reason,
            'date': adv.created_at.strftime('%Y-%m-%d'),
            'by': (adv.created_by.get_full_name() or adv.created_by.username) if adv.created_by else '—',
        } for adv in advances_qs]

        data.append({
            'barber_id': barber.id,
            'barber_name': barber.display_name,
            'total_commissions': total_commissions,
            'total_tips': total_tips,
            'total_earnings': total_earnings,
            'total_advances': total_advances,
            'net_payable': net_payable,
            'history': history,
            'advances': advances,
        })

    # Ordenar por nombre
    data.sort(key=lambda x: x['barber_name'])

    return Response({'payments': data})


@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def register_barber_advance_view(request, barber_id):
    """POST /api/admin/cashflow/barber-payments/<id>/advance/ - Registra un vale/adelanto.

    El barbero pide prestado parte de lo que ha hecho. El monto no puede superar el
    saldo disponible (acumulado pendiente menos vales ya pendientes).
    """
    from apps.cashflow.models import Commission, BarberAdvance
    from apps.barbers.models import Barber
    from django.db.models import Sum
    from decimal import Decimal, InvalidOperation

    try:
        barber = Barber.objects.get(id=barber_id)
    except Barber.DoesNotExist:
        return Response({'error': 'Barbero no encontrado'}, status=404)

    raw_amount = request.data.get('amount')
    reason = (request.data.get('reason') or '').strip()
    try:
        amount = Decimal(str(raw_amount)).quantize(Decimal('1'))
    except (InvalidOperation, TypeError, ValueError):
        return Response({'error': 'Monto inválido.'}, status=400)
    if amount <= 0:
        return Response({'error': 'El monto del vale debe ser mayor a cero.'}, status=400)

    # Saldo disponible = comisiones+propinas no pagadas − vales pendientes.
    earnings = Commission.objects.filter(
        barber_id=barber_id, is_paid=False, sale__approval_status='approved'
    ).aggregate(t=Sum('total_earnings'))['t'] or Decimal('0')
    outstanding = BarberAdvance.objects.filter(
        barber_id=barber_id, is_settled=False
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    available = Decimal(earnings) - Decimal(outstanding)

    if amount > available:
        return Response({
            'error': f'El vale (${amount:,.0f}) supera el saldo disponible del barbero (${available:,.0f}).'
        }, status=400)

    advance = BarberAdvance.objects.create(
        barber=barber, amount=amount, reason=reason, created_by=request.user
    )

    log_audit(
        user=request.user,
        action='create',
        obj=advance,
        changes={'amount': float(amount)},
        request=request,
        extra_data={'msg': f"Registró un vale/adelanto de ${amount:,.0f} a {barber.display_name}" + (f" — {reason}" if reason else "")}
    )

    return Response({
        'ok': True,
        'message': f'Vale de ${amount:,.0f} registrado para {barber.display_name}.'
    }, status=201)


@api_view(['DELETE'])
@permission_classes([IsOperationalAdminOrAbove])
def delete_barber_advance_view(request, advance_id):
    """DELETE /api/admin/cashflow/barber-payments/advance/<id>/ - Anula un vale pendiente."""
    from apps.cashflow.models import BarberAdvance

    try:
        advance = BarberAdvance.objects.select_related('barber').get(id=advance_id)
    except BarberAdvance.DoesNotExist:
        return Response({'error': 'Vale no encontrado.'}, status=404)

    if advance.is_settled:
        return Response({'error': 'No se puede anular un vale ya liquidado.'}, status=400)

    barber_name = advance.barber.display_name if advance.barber else '?'
    amount = float(advance.amount)
    advance.delete()

    log_audit(
        user=request.user,
        action='delete',
        obj=None,
        changes={},
        request=request,
        extra_data={'msg': f"Anuló un vale/adelanto de ${amount:,.0f} de {barber_name}"}
    )
    return Response({'ok': True, 'message': 'Vale anulado.'})

@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def pay_barber_view(request, barber_id):
    """POST /api/admin/cashflow/barber-payments/<id>/pay/ - Liquida el saldo de un barbero.

    Marca como pagadas las comisiones pendientes y como liquidados los vales/adelantos
    pendientes. El monto que recibe el barbero es el neto (acumulado − vales).
    """
    from apps.cashflow.models import Commission, BarberAdvance
    from apps.barbers.models import Barber
    from django.utils import timezone
    from django.db import transaction
    from django.db.models import Sum
    from decimal import Decimal

    try:
        barber = Barber.objects.get(id=barber_id)
    except Barber.DoesNotExist:
        return Response({'error': 'Barbero no encontrado'}, status=404)

    with transaction.atomic():
        unpaid = Commission.objects.filter(
            barber_id=barber_id,
            is_paid=False,
            sale__approval_status='approved'
        )
        advances = BarberAdvance.objects.filter(barber_id=barber_id, is_settled=False)

        earnings = Decimal(unpaid.aggregate(total=Sum('total_earnings'))['total'] or 0)
        total_advances = Decimal(advances.aggregate(total=Sum('amount'))['total'] or 0)
        net_amount = earnings - total_advances

        if earnings == 0 and total_advances == 0:
            return Response({'error': 'El barbero no tiene saldo pendiente por pagar.'}, status=400)

        if net_amount < 0:
            return Response({
                'error': f'Los vales pendientes (${total_advances:,.0f}) superan el acumulado (${earnings:,.0f}). Anula algún vale antes de liquidar.'
            }, status=400)

        now = timezone.now()
        unpaid.update(is_paid=True, paid_at=now)
        advances.update(is_settled=True, settled_at=now)

        msg = f"Liquidó a {barber.display_name}: ${net_amount:,.0f} neto (acumulado ${earnings:,.0f}"
        if total_advances > 0:
            msg += f" − vales ${total_advances:,.0f}"
        msg += ")"
        log_audit(
            user=request.user,
            action='update',
            obj=None,
            changes={'is_paid': True},
            request=request,
            extra_data={'msg': msg}
        )

    return Response({
        'ok': True,
        'message': f'Liquidación de ${net_amount:,.0f} netos registrada para {barber.display_name} (acumulado ${earnings:,.0f}, vales ${total_advances:,.0f}).'
    })


@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def edit_sale_payment_method_view(request, sale_id):
    """POST /api/admin/cashflow/sales/<id>/edit-payment/"""
    from apps.cashflow.models import Sale, PaymentMethod
    try:
        sale = Sale.objects.get(pk=sale_id)
        pm_id = request.data.get('payment_method_id')
        if not pm_id:
            return Response({'error': 'El método de pago es obligatorio.'}, status=400)
            
        pm = PaymentMethod.objects.get(pk=pm_id)
        old_pm_name = sale.payment_method.name if sale.payment_method else 'Ninguno'
        sale.payment_method = pm
        sale.save(update_fields=['payment_method'])
        
        log_audit(
            user=request.user,
            action='update',
            obj=sale,
            changes={'payment_method': [old_pm_name, pm.name]},
            request=request,
            extra_data={'msg': f"Cambió método de pago de venta #{sale.id} ({old_pm_name} -> {pm.name})"}
        )
        return Response({'ok': True, 'message': 'Método de pago actualizado.'})
    except Sale.DoesNotExist:
        return Response({'error': 'Venta no encontrada.'}, status=404)
    except PaymentMethod.DoesNotExist:
        return Response({'error': 'Método de pago no encontrado.'}, status=404)


@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def edit_inventory_sale_payment_method_view(request, sale_id):
    """POST /api/admin/cashflow/inventory-sales/<id>/edit-payment/"""
    from apps.cashflow.models import InventorySale, PaymentMethod
    try:
        sale = InventorySale.objects.get(pk=sale_id)
        pm_id = request.data.get('payment_method_id')
        if not pm_id:
            return Response({'error': 'El método de pago es obligatorio.'}, status=400)
            
        pm = PaymentMethod.objects.get(pk=pm_id)
        old_pm_name = sale.payment_method.name if sale.payment_method else 'Ninguno'
        sale.payment_method = pm
        sale.save(update_fields=['payment_method'])
        
        log_audit(
            user=request.user,
            action='update',
            obj=sale,
            changes={'payment_method': [old_pm_name, pm.name]},
            request=request,
            extra_data={'msg': f"Cambió método de pago de venta de inventario #{sale.id} ({old_pm_name} -> {pm.name})"}
        )
        return Response({'ok': True, 'message': 'Método de pago actualizado.'})
    except InventorySale.DoesNotExist:
        return Response({'error': 'Venta de inventario no encontrada.'}, status=404)
    except PaymentMethod.DoesNotExist:
        return Response({'error': 'Método de pago no encontrado.'}, status=404)
