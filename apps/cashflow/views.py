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


def _cash_income_for(sales_qs, inventory_qs):
    """Efectivo físico que entra a caja: ventas y productos pagados en efectivo
    o sin método (paridad con el label 'Efectivo/Sin Especificar' del detalle),
    INCLUYENDO propinas — están físicamente en la caja aunque sean pass-through.
    """
    from django.db.models import Q, Sum, F
    cash_q = Q(payment_method__isnull=True) | Q(payment_method__slug='efectivo')
    s = sales_qs.filter(cash_q).aggregate(t=Sum(F('final_price') + F('tip_amount')))['t'] or Decimal('0')
    i = inventory_qs.filter(cash_q).aggregate(t=Sum('total_price'))['t'] or Decimal('0')
    return Decimal(s) + Decimal(i)

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

    # ── Control de acceso (SEC-08) ──────────────────────────────────────────
    # Un barbero "puro" (sin rol admin) solo puede hacer checkout de SUS propias
    # reservas; de lo contrario podría facturar la agenda de otro (IDOR).
    profile = getattr(request.user, 'profile', None)
    request_barber = getattr(request.user, 'barber_profile', None)
    is_pure_barber = bool(profile and profile.is_barber and not profile.is_admin)
    if is_pure_barber:
        if request_barber is None or booking.barber_id != request_barber.id:
            return Response(
                {'error': 'No puedes hacer checkout de una reserva que no es tuya.'},
                status=status.HTTP_403_FORBIDDEN,
            )

    # Los costos de materiales/mano de obra de Frank reemplazan el base_price,
    # así que solo pueden enviarlos los admins o el propio Frank. Un barbero
    # normal no debe poder inflar/alterar la base de la venta.
    can_send_frank_costs = bool(profile and profile.is_admin) or (
        request_barber is not None and request_barber.is_frank
    )
    if can_send_frank_costs:
        frank_materials_cost = _safe_decimal(data.get('frank_materials_cost'), 0)
        frank_labor_cost = _safe_decimal(data.get('frank_labor_cost'), 0)
    else:
        frank_materials_cost = Decimal(0)
        frank_labor_cost = Decimal(0)

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
            frank_materials_cost=frank_materials_cost,
            frank_labor_cost=frank_labor_cost,
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

    Body opcional (pago diario de Frank):
      frank_pay_enabled: bool  — si se le paga hoy (chulo del modal)
      frank_pay_amount: int    — monto realmente entregado (editable)
      force_cash: bool         — confirma un pago que supera el efectivo del día
    """
    from apps.cashflow.models import DailyClose, Expense, Sale, Commission, InventorySale, BarberAdvance, BarberPayment
    from django.db.models import Sum
    from django.db import transaction
    from django.utils import timezone

    today = timezone.localtime(timezone.now()).date()

    body = request.data or {}
    frank_pay_enabled = bool(body.get('frank_pay_enabled', False))
    frank_pay_amount = _safe_decimal(body.get('frank_pay_amount', 0))
    force_cash = bool(body.get('force_cash', False))
    if frank_pay_enabled and frank_pay_amount < 0:
        return Response({'error': 'El monto del pago a Franko no puede ser negativo.'}, status=status.HTTP_400_BAD_REQUEST)

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
        # Solo un cierre por día. El chequeo va DENTRO del atomic (junto a la
        # creación) para cerrar la ventana de carrera entre exists() y create();
        # el UniqueConstraint sobre `date` es el respaldo definitivo en BD.
        if DailyClose.objects.filter(date=today).exists():
            return Response({'error': 'El cierre de caja para el día de hoy ya fue generado.'}, status=status.HTTP_400_BAD_REQUEST)

        total_tips = pending_sales.aggregate(total=Sum('tip_amount'))['total'] or 0

        # Ventas de inventario
        total_inventory_sales = pending_inventory_sales.aggregate(total=Sum('total_price'))['total'] or 0

        # Comisiones
        commissions = Commission.objects.filter(sale__in=pending_sales)

        # Separar a Franko. Solo las comisiones NO pagadas: si una ya se liquidó
        # (o el cierre se rehízo), no se debe volver a pagar.
        frank_barber = cashflow_services.get_frank_barber()
        frank_commissions = commissions.filter(
            barber__display_name__icontains='frank', is_paid=False
        )
        frank_total_comm = frank_commissions.aggregate(total=Sum('commission_amount'))['total'] or 0

        # Comisiones de los demás (40%)
        other_commissions = commissions.exclude(barber__display_name__icontains='frank')
        total_commissions = other_commissions.aggregate(total=Sum('commission_amount'))['total'] or 0

        # ── Pago diario de Frank (chulo + monto editable) ──────────────
        # El saldo se deriva del ledger (ganado − vales − pagos) ANTES de
        # registrar nada de este cierre. Si se paga menos que lo sugerido, el
        # resto queda como saldo a favor de Frank; si se paga más, queda deuda.
        ledger = cashflow_services.compute_frank_ledger()
        frank_suggested = ledger['suggested_payment']
        cash_income = _cash_income_for(pending_sales, pending_inventory_sales)

        frank_paid = Decimal('0')
        frank_expense = None
        if frank_pay_enabled and frank_barber:
            frank_paid = frank_pay_amount
            # El pago de Frank sale SOLO del efectivo del día.
            if frank_paid > cash_income and not force_cash:
                return Response({
                    'error': f'El pago a Franko (${frank_paid:,.0f}) supera el efectivo del día (${cash_income:,.0f}).',
                    'code': 'cash_exceeded',
                    'cash_available': float(cash_income),
                }, status=status.HTTP_400_BAD_REQUEST)
            if frank_paid > 0:
                frank_expense = Expense.objects.create(
                    description="Pago Diario: Franko",
                    amount=frank_paid,
                    expense_type='variable',
                    registered_by=request.user
                )

        # Las comisiones de Frank SIEMPRE se marcan procesadas por este cierre
        # (se pague lo que se pague): `is_paid` significa "procesada en un
        # cierre", no "pagada completa". El saldo real vive en el ledger.
        frank_commissions.update(is_paid=True, is_paid_in_daily_close=True, paid_at=timezone.now())

        # Egresos variables del día (no asignados a un cierre).
        # OJO: este total INCLUYE el "Pago Diario: Franko" recién creado.
        pending_expenses = Expense.objects.filter(included_in_daily_close__isnull=True)
        total_expenses = pending_expenses.aggregate(total=Sum('amount'))['total'] or 0

        # Ingreso neto (fórmula única centralizada en cashflow.services). El
        # neto es DEVENGADO: resta la comisión devengada de Frank del día, no
        # el monto pagado — pagar de más/de menos es movimiento de deuda, no
        # utilidad. Para el gasto real quitamos el rubro "Pago Diario: Franko".
        total_final_prices = pending_sales.aggregate(total=Sum('final_price'))['total'] or 0
        real_expenses = total_expenses - frank_paid
        net_income = cashflow_services.compute_live_net_income(
            service_revenue=total_final_prices,
            inventory_revenue=total_inventory_sales,
            non_frank_commissions=total_commissions,
            real_expenses=real_expenses,
            frank_commission=frank_total_comm,
        )

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

        if frank_paid > 0 and frank_barber:
            # Registro del pago real (ledger). CASCADE con el cierre: si el
            # cierre se borra, el pago desaparece y el saldo se restaura solo.
            BarberPayment.objects.create(
                barber=frank_barber,
                daily_close=daily_close,
                expense=frank_expense,
                amount=frank_paid,
                suggested_amount=frank_suggested,
                created_by=request.user,
            )
            # Liquidar los vales pendientes de Frank: ya quedaron descontados
            # en el saldo con el que se calculó este pago.
            BarberAdvance.objects.filter(barber=frank_barber, is_settled=False).update(
                is_settled=True, settled_at=timezone.now(), settled_in_daily_close=daily_close
            )

        # Update sales and expenses
        pending_sales.update(included_in_daily_close=daily_close)
        pending_inventory_sales.update(included_in_daily_close=daily_close)
        pending_expenses.update(included_in_daily_close=daily_close)

        # Audit log
        frank_msg = ''
        if frank_barber:
            if frank_paid > 0:
                frank_msg = f". Pago a Franko: ${frank_paid:,.0f} (sugerido ${frank_suggested:,.0f})"
            elif frank_pay_enabled:
                frank_msg = ". Pago a Franko: $0"
            else:
                frank_msg = ". Sin pago a Franko (queda acumulado)"
        log_audit(
            user=request.user,
            action='daily_close',
            obj=daily_close,
            changes={
                'frank_pay_enabled': frank_pay_enabled,
                'frank_paid': str(frank_paid),
                'frank_suggested': str(frank_suggested),
            },
            request=request,
            extra_data={'msg': f"Realizó el Cierre de Caja del {today} con Neto ${net_income:,.0f}{frank_msg}"}
        )

    return Response({
        'message': 'Cierre de caja exitoso',
        'close_id': daily_close.id,
        'net_income': daily_close.net_income,
    })


@api_view(['GET'])
@permission_classes([IsOperationalAdminOrAbove])
def daily_close_preview_view(request):
    """GET /api/admin/cashflow/daily-close/preview/ - Datos para el modal de cierre.

    Devuelve el saldo corriente de Frank (sugerido de pago) y el efectivo del
    día, para que el operador decida el chulo y el monto antes de cerrar.
    """
    from apps.cashflow.models import Sale, InventorySale

    pending_sales = Sale.objects.filter(
        approval_status=Sale.STATUS_APPROVED, included_in_daily_close__isnull=True
    )
    pending_inventory_sales = InventorySale.objects.filter(included_in_daily_close__isnull=True)
    pending_approvals_count = Sale.objects.filter(
        approval_status=Sale.STATUS_PENDING, included_in_daily_close__isnull=True
    ).count()

    ledger = cashflow_services.compute_frank_ledger()

    return Response({
        'frank': {
            'exists': ledger['exists'],
            'unpaid_earnings': float(ledger['unpaid_earnings']),
            'unsettled_advances': float(ledger['unsettled_advances']),
            'balance': float(ledger['balance']),
            'suggested': float(ledger['suggested_payment']),
        },
        'cash': {
            'cash_income': float(_cash_income_for(pending_sales, pending_inventory_sales)),
        },
        'pending_sales_count': pending_sales.count() + pending_inventory_sales.count(),
        'pending_approvals_count': pending_approvals_count,
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

    # Detalle de egresos. Los materiales se marcan aparte para poder mostrarlos
    # como su propio rubro: siguen sumando en total_expenses igual que antes.
    expenses_data = []
    total_materials = 0.0
    for exp in expenses:
        amt = float(exp.amount)
        is_materials = cashflow_services.is_materials_expense(exp.description)
        if is_materials:
            total_materials += amt
        expenses_data.append({
            'description': exp.description,
            'amount': amt,
            'type': exp.get_expense_type_display() if hasattr(exp, 'get_expense_type_display') else exp.expense_type,
            'is_materials': is_materials,
        })

    # Pago real a Frank en este cierre (ledger) y resumen del efectivo.
    frank_payment = daily_close.barber_payments.first()
    cash_income = _cash_income_for(sales, inventory_sales)
    frank_paid = float(frank_payment.amount) if frank_payment else 0.0

    return Response({
        'id': daily_close.id,
        'date': daily_close.date.strftime('%Y-%m-%d'),
        'closed_at': timezone.localtime(daily_close.closed_at).strftime('%Y-%m-%d %H:%M:%S'),
        'closed_by': daily_close.closed_by.username,
        'closed_by_name': daily_close.closed_by.get_full_name() or daily_close.closed_by.username,
        'frank_payment': {
            'amount': float(frank_payment.amount),
            'suggested_amount': float(frank_payment.suggested_amount),
            'by': (frank_payment.created_by.get_full_name() or frank_payment.created_by.username) if frank_payment.created_by else '—',
        } if frank_payment else None,
        'cash_summary': {
            'cash_income': float(cash_income),
            'frank_paid': frank_paid,
            'cash_net': float(cash_income) - frank_paid,
        },
        'total_sales': float(daily_close.total_sales),
        'total_inventory_sales': float(daily_close.total_inventory_sales),
        'total_tips': float(daily_close.total_tips),
        'total_commissions': float(daily_close.total_commissions),
        'total_expenses': float(daily_close.total_expenses),
        # Subconjunto de total_expenses, no un rubro nuevo: informativo.
        'total_materials': total_materials,
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
    from apps.cashflow.models import DailyClose, Commission
    from django.db import transaction
    try:
        daily_close = DailyClose.objects.get(pk=close_id)
        date_str = daily_close.date.strftime('%Y-%m-%d')

        with transaction.atomic():
            # Revertir el pago automático de Frank ANTES de desvincular: si no,
            # al recerrar se crearía un segundo "Pago Diario: Franko" y se
            # duplicaría el egreso. Se hace mientras las ventas/egresos siguen
            # ligados a este cierre.
            Commission.objects.filter(
                sale__included_in_daily_close=daily_close,
                is_paid_in_daily_close=True,
            ).update(is_paid=False, is_paid_in_daily_close=False, paid_at=None)
            daily_close.expenses.filter(
                description__startswith='Pago Diario: Franko'
            ).delete()

            # Des-liquidar los vales de Frank liquidados por este cierre: al
            # recerrar vuelven a descontarse del sugerido.
            daily_close.settled_advances.update(
                is_settled=False, settled_at=None, settled_in_daily_close=None
            )
            # El BarberPayment de este cierre cae solo por CASCADE al borrar el
            # cierre — el saldo derivado del ledger se restaura automáticamente.

            # Desvincular las ventas y egresos restantes (vuelven a pendientes).
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
    total_materials = 0.0
    for exp in expenses:
        amt = float(exp.amount)
        total_expenses_overall += amt
        is_materials = cashflow_services.is_materials_expense(exp.description)
        if is_materials:
            total_materials += amt
        expenses_data.append({
            'description': exp.description,
            'amount': amt,
            'type': exp.get_expense_type_display() if hasattr(exp, 'get_expense_type_display') else exp.expense_type,
            'is_materials': is_materials,
        })

    # El rubro sintético del pago a Frank refleja el DEVENGADO DEL DÍA
    # (comisión + propinas de hoy), para que el KPI "Egresos" sea comparable
    # con el del cierre (que registra el egreso del día). El saldo corriente
    # con arrastre se expone aparte en `frank_ledger` para el modal de cierre.
    ledger = cashflow_services.compute_frank_ledger()
    if frank_pay_live > 0:
        expenses_data.append({
            'description': 'Pago Diario: Franko (devengado del día)',
            'amount': frank_pay_live,
            'type': 'Variable'
        })
        total_expenses_overall += frank_pay_live

    # Ingreso neto con la fórmula única (cashflow.services). El neto es
    # DEVENGADO: usa la comisión de Frank generada HOY (frank_commission_live).
    # Para el gasto real quitamos el rubro sintético (comisión + propina de
    # Frank), ya que la propina es pass-through (cash que entra y sale).
    frank_commission_live = frank_pay_live - frank_tips_live
    real_expenses = total_expenses_overall - frank_pay_live
    net_income = float(cashflow_services.compute_live_net_income(
        service_revenue=total_sales_overall,
        inventory_revenue=total_inventory_sales_overall,
        non_frank_commissions=total_commissions_overall,
        real_expenses=real_expenses,
        frank_commission=frank_commission_live,
    ))

    cash_income_live = float(_cash_income_for(approved_sales, inventory_sales))

    return Response({
        'date': today.strftime('%Y-%m-%d'),
        'total_sales': total_sales_overall,
        'total_inventory_sales': total_inventory_sales_overall,
        'total_tips': total_tips_overall,
        'total_commissions': total_commissions_overall,
        'total_expenses': total_expenses_overall,
        # Subconjunto de total_expenses, no un rubro nuevo: informativo.
        'total_materials': total_materials,
        'net_income': net_income,
        'pending_approvals_count': pending_approvals_count,
        'frank_ledger': {
            'balance': float(ledger['balance']),
            'suggested': float(ledger['suggested_payment']),
            'unsettled_advances': float(ledger['unsettled_advances']),
        },
        'cash_summary': {
            'cash_income': cash_income_live,
        },
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


@api_view(['POST'])
@permission_classes([IsOperationalAdminOrAbove])
def edit_expense_view(request, expense_id):
    """POST /api/admin/cashflow/expenses/<id>/edit/ - Editar un egreso (auditado).

    Reglas:
    - Egresos generados por el sistema (Pago Diario: Franko, materiales de una
      venta) no se editan: desincronizarían el ledger / la trazabilidad.
    - Egreso ya incluido en un cierre: monto y tipo quedan bloqueados para
      todos (DailyClose es inmutable; el camino es borrar cierre → editar →
      recerrar). Superadmin sí puede corregir descripción/notas/imagen.
    - operational_admin (Frank): solo egresos variables y sin cambiar el tipo
      (espeja la restricción de creación).
    Todo cambio queda en AuditLog con {campo: [antes, después]}.
    """
    from apps.cashflow.models import Expense

    try:
        expense = Expense.objects.get(pk=expense_id)
    except Expense.DoesNotExist:
        return Response({'error': 'Egreso no encontrado.'}, status=404)

    # 1. Egresos automáticos del sistema: intocables.
    if (expense.description.startswith('Pago Diario: Franko')
            or '(venta #' in expense.description
            or expense.barber_payments.exists()):
        return Response({'error': 'Este egreso fue generado automáticamente por el sistema y no se puede editar.'}, status=400)

    profile = getattr(request.user, 'profile', None)
    is_superadmin = bool(profile and profile.is_superadmin)

    data = request.data
    new_description = (data.get('description') or '').strip() or None
    new_amount_raw = data.get('amount')
    new_expense_type = data.get('expense_type') or None
    new_notes = data.get('notes') if 'notes' in data else None
    new_image = request.FILES.get('image') if hasattr(request, 'FILES') else None

    # 2. Restricción de rol: Frank solo egresos variables, sin cambiar el tipo.
    if not is_superadmin:
        if expense.expense_type != 'variable':
            return Response({'error': 'Solo los administradores principales pueden editar egresos fijos o de inventario.'}, status=403)
        if new_expense_type and new_expense_type != 'variable':
            return Response({'error': 'Solo los administradores principales pueden cambiar el tipo de un egreso.'}, status=403)

    # 3. Egreso ya cerrado: monto y tipo bloqueados para todos.
    is_closed = expense.included_in_daily_close_id is not None
    if is_closed:
        wants_amount = new_amount_raw is not None and str(new_amount_raw).strip() != '' and _safe_decimal(new_amount_raw) != expense.amount
        wants_type = new_expense_type and new_expense_type != expense.expense_type
        if wants_amount or wants_type:
            close_date = expense.included_in_daily_close.date.strftime('%d/%m/%Y')
            return Response({'error': f'Este egreso pertenece al cierre del {close_date}. Para corregir monto o tipo, un superadmin debe eliminar ese cierre, editar y volver a cerrar.'}, status=400)
        if not is_superadmin:
            return Response({'error': 'Este egreso ya está incluido en un cierre; solo un superadmin puede corregir su descripción o notas.'}, status=403)

    # La nueva descripción no puede adoptar un patrón reservado del sistema:
    # delete_daily_close_view borra por prefijo "Pago Diario: Franko" y los
    # egresos de materiales se identifican por "(venta #". Renombrar hacia
    # ellos causaría borrados/tratamientos incorrectos.
    if new_description and (new_description.startswith('Pago Diario: Franko') or '(venta #' in new_description):
        return Response({'error': 'La descripción no puede usar un patrón reservado del sistema ("Pago Diario: Franko" o "(venta #").'}, status=400)

    changes = {}

    if new_description and new_description != expense.description:
        changes['description'] = [expense.description, new_description]
        expense.description = new_description

    if new_amount_raw is not None and str(new_amount_raw).strip() != '':
        try:
            new_amount = Decimal(str(new_amount_raw)).quantize(Decimal('1'))
            if new_amount <= 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError, TypeError):
            return Response({'error': 'Monto inválido.'}, status=400)
        if new_amount != expense.amount:
            changes['amount'] = [str(expense.amount), str(new_amount)]
            expense.amount = new_amount

    valid_types = {t[0] for t in Expense.EXPENSE_TYPES}
    if new_expense_type and new_expense_type != expense.expense_type:
        if new_expense_type not in valid_types:
            return Response({'error': 'Tipo de egreso inválido.'}, status=400)
        changes['expense_type'] = [expense.expense_type, new_expense_type]
        expense.expense_type = new_expense_type

    if new_notes is not None and new_notes != expense.notes:
        changes['notes'] = [expense.notes, new_notes]
        expense.notes = new_notes

    if new_image:
        changes['image'] = [expense.image.name if expense.image else '', new_image.name]
        expense.image = new_image

    if not changes:
        return Response({'ok': True, 'message': 'Sin cambios.'})

    expense.save()

    changed_fields = ', '.join(changes.keys())
    log_audit(
        user=request.user,
        action='update',
        obj=expense,
        changes=changes,
        request=request,
        extra_data={'msg': f"Editó el egreso #{expense.id} ({expense.description}): {changed_fields}"}
    )
    return Response({'ok': True, 'message': 'Egreso actualizado correctamente.'})


@api_view(['GET'])
@permission_classes([IsOperationalAdminOrAbove])
def daily_closes_list_view(request):
    """GET /api/admin/cashflow/daily-closes/?date_from=&date_to= - Historial de cierres.

    Sin filtros devuelve los últimos 10 (paridad con la vista anterior);
    con filtros devuelve todo el rango.
    """
    from apps.cashflow.models import DailyClose
    from datetime import datetime

    def _parse(value):
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None

    closes = DailyClose.objects.select_related('closed_by').prefetch_related(
        'barber_payments').order_by('-date', '-closed_at')

    date_from = _parse(request.query_params.get('date_from'))
    date_to = _parse(request.query_params.get('date_to'))
    if date_from:
        closes = closes.filter(date__gte=date_from)
    if date_to:
        closes = closes.filter(date__lte=date_to)

    is_filtered = bool(date_from or date_to)
    if not is_filtered:
        closes = closes[:10]

    data = []
    for close in closes:
        payment = next(iter(close.barber_payments.all()), None)
        data.append({
            'id': close.id,
            'date': close.date.strftime('%Y-%m-%d'),
            'date_display': tz.localtime(close.closed_at).strftime('%d/%m/%Y') if close.closed_at else close.date.strftime('%d/%m/%Y'),
            'closed_at_time': tz.localtime(close.closed_at).strftime('%I:%M %p') if close.closed_at else '',
            'closed_by_name': close.closed_by.get_full_name() or close.closed_by.username,
            'total_sales': float(close.total_sales),
            'total_commissions': float(close.total_commissions),
            'total_expenses': float(close.total_expenses),
            'net_income': float(close.net_income),
            'is_verified': close.is_verified,
            'frank_paid': float(payment.amount) if payment else None,
        })

    return Response({'closes': data, 'is_filtered': is_filtered, 'count': len(data)})


@api_view(['GET'])
@permission_classes([IsOperationalAdminOrAbove])
def cashflow_alerts_view(request):
    """GET /api/admin/cashflow/alerts/ - Alertas operativas para el panel.

    - unclosed: citas de hoy sin checkout hace más de ~3 horas.
    - close_pending: ya son ≥9 pm, no hay cierre de hoy y quedan movimientos.
    """
    from django.utils import timezone
    from apps.cashflow.models import DailyClose, Sale, InventorySale
    from apps.cashflow.alerts import get_unclosed_bookings

    unclosed = get_unclosed_bookings()
    unclosed_data = [{
        'id': b.id,
        'client_name': b.client_name,
        'barber_name': b.barber.display_name if b.barber else 'Sin barbero',
        'service_name': b.service.name if b.service else 'Servicio',
        'time': b.time.strftime('%I:%M %p'),
    } for b in unclosed]

    now_local = timezone.localtime()
    close_pending = False
    if now_local.hour >= 21 and not DailyClose.objects.filter(date=now_local.date()).exists():
        # Solo hay algo cerrable si existen ventas APROBADAS o inventario
        # pendientes (mismas condiciones que daily_close_view y el recordatorio
        # por email); un egreso o una venta sin aprobar no habilita el cierre.
        close_pending = (
            Sale.objects.filter(
                approval_status=Sale.STATUS_APPROVED, included_in_daily_close__isnull=True
            ).exists()
            or InventorySale.objects.filter(included_in_daily_close__isnull=True).exists()
        )

    return Response({
        'unclosed': unclosed_data,
        'unclosed_count': len(unclosed_data),
        'close_pending': close_pending,
    })


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
            # Solo revertir los consumos que NO se hayan revertido antes. Si la
            # venta se re-facturó y se vuelve a rechazar, los movimientos viejos
            # ya están marcados y se omiten — así no devolvemos stock dos veces
            # (BIZ-07). Como InventoryMovement no tiene FK a Sale ni flag propio,
            # marcamos el movimiento original con un sufijo en `notes`.
            consumptions = InventoryMovement.objects.filter(
                booking=booking, movement_type='out'
            ).exclude(notes__icontains='[revertido').select_related('item')
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
                # Marcar el consumo original como revertido para no devolverlo
                # de nuevo si hay un futuro rechazo de una re-facturación.
                marker = f' [revertido venta #{sale.id}]'
                mov.notes = (mov.notes or '')[:300 - len(marker)] + marker
                mov.save(update_fields=['notes'])

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
    from apps.cashflow.models import Commission, DailyClose, Expense, BarberPayment
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
            expense = close.expenses.filter(description__startswith='Pago Diario: Franko').first()

            # ¿Ya hay un pago registrado en el ledger para este cierre?
            existing_payment = BarberPayment.objects.filter(
                barber=frank, daily_close=close
            ).first()
            # Un pago de "backfill"/legacy (marcado con 'legacy' en notes) refleja
            # el devengado automático viejo y DEBE realinearse cuando fix-frank
            # recalcula las comisiones al 50%; un pago del modal (notes vacío) fue
            # una decisión humana (chulo + monto editable) y NO se toca.
            is_human_payment = bool(existing_payment and 'legacy' not in (existing_payment.notes or ''))

            if is_human_payment:
                frank_expense_amount = existing_payment.amount
                frank_comms.update(is_paid=True, is_paid_in_daily_close=True, paid_at=close.closed_at or timezone.now())
            elif frank_pay > 0:
                # Cierre legacy / pago de backfill: se ajusta el egreso y el
                # BarberPayment al devengado recalculado para que el ledger netee.
                if expense:
                    Expense.objects.filter(id=expense.id).update(amount=frank_pay)
                else:
                    expense = Expense.objects.create(
                        description='Pago Diario: Franko',
                        amount=frank_pay,
                        expense_type='variable',
                        registered_by=close.closed_by,
                        included_in_daily_close=close
                    )
                if existing_payment:
                    existing_payment.amount = frank_pay
                    existing_payment.suggested_amount = frank_pay
                    existing_payment.expense = expense
                    existing_payment.notes = 'Realineado por fix-frank-history (legacy)'
                    existing_payment.save(update_fields=['amount', 'suggested_amount', 'expense', 'notes'])
                else:
                    BarberPayment.objects.create(
                        barber=frank,
                        daily_close=close,
                        expense=expense,
                        amount=frank_pay,
                        suggested_amount=frank_pay,
                        notes='Registrado por fix-frank-history (pago automático legacy)',
                    )
                frank_expense_amount = frank_pay
                frank_comms.update(is_paid=True, is_paid_in_daily_close=True, paid_at=close.closed_at or timezone.now())
            else:
                # Sin devengado: borrar el egreso y el pago de backfill (si es legacy).
                if expense:
                    expense.delete()
                if existing_payment:
                    existing_payment.delete()
                frank_expense_amount = Decimal('0')

            # Recalcular totales del cierre
            total_expenses = close.expenses.aggregate(total=Sum('amount'))['total'] or 0
            total_sales = sales.aggregate(total=Sum('final_price'))['total'] or 0
            total_tips = sales.aggregate(total=Sum('tip_amount'))['total'] or 0
            total_inventory = close.inventory_sales.aggregate(total=Sum('total_price'))['total'] or 0

            # Fórmula canónica (misma del cierre): neto devengado — comisión
            # devengada de Frank + gastos reales sin el rubro de su pago.
            net_income = cashflow_services.compute_live_net_income(
                service_revenue=total_sales,
                inventory_revenue=total_inventory,
                non_frank_commissions=total_other_comms,
                real_expenses=Decimal(total_expenses) - Decimal(frank_expense_amount),
                frank_commission=frank_total_comm,
            )

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
    from django.db.models import F
    from decimal import Decimal

    data = request.data
    item_id = data.get('item_id')
    quantity = data.get('quantity', 1)
    payment_method_id = data.get('payment_method_id')

    try:
        quantity = Decimal(str(quantity))
        if quantity <= 0:
            return Response({'error': 'La cantidad debe ser mayor a 0'}, status=400)
    except Exception:
        return Response({'error': 'Cantidad inválida'}, status=400)

    if not InventoryItem.objects.filter(pk=item_id).exists():
        return Response({'error': 'Producto no encontrado'}, status=404)

    payment_method = None
    if payment_method_id:
        payment_method = PaymentMethod.objects.filter(id=payment_method_id).first()

    with transaction.atomic():
        # Bloquear la fila del producto para evitar sobreventa por carrera
        # (dos ventas simultáneas leyendo el mismo stock). Si no hay
        # existencias suficientes se AVISA con error, en vez de fijar el
        # stock a 0 en silencio.
        item = InventoryItem.objects.select_for_update().get(pk=item_id)
        if item.quantity < quantity:
            return Response({
                'error': f'Stock insuficiente: quedan {item.quantity} {item.unit} de "{item.name}".'
            }, status=400)

        # Restar del inventario de forma atómica (F evita la condición de carrera).
        qty_before = item.quantity
        InventoryItem.objects.filter(pk=item.pk).update(quantity=F('quantity') - quantity)
        item.refresh_from_db(fields=['quantity'])

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
            'is_frank': False,
            'total_commissions': total_commissions,
            'total_tips': total_tips,
            'total_earnings': total_earnings,
            'total_advances': total_advances,
            'net_payable': net_payable,
            'history': history,
            'advances': advances,
        })

    # Card de Frank: su pago se automatiza en el cierre diario, pero su saldo
    # corriente (que puede ser negativo) y sus vales sí se gestionan aquí.
    frank = cashflow_services.get_frank_barber()
    if frank:
        ledger = cashflow_services.compute_frank_ledger()

        frank_daily = Commission.objects.filter(
            barber=frank, is_paid=False, sale__approval_status='approved'
        ).annotate(date=TruncDate('created_at')).values('date').annotate(
            daily_total=Sum('total_earnings'),
            daily_commissions=Sum('commission_amount'),
            daily_tips=Sum('tip_amount')
        ).order_by('-date')
        frank_history = [{
            'date': day['date'].strftime('%Y-%m-%d'),
            'total': float(day['daily_total'] or 0),
            'commissions': float(day['daily_commissions'] or 0),
            'tips': float(day['daily_tips'] or 0),
        } for day in frank_daily if day['date']]

        frank_advances_qs = BarberAdvance.objects.filter(
            barber=frank, is_settled=False
        ).select_related('created_by').order_by('-created_at')
        frank_advances = [{
            'id': adv.id,
            'amount': float(adv.amount),
            'reason': adv.reason,
            'date': adv.created_at.strftime('%Y-%m-%d'),
            'by': (adv.created_by.get_full_name() or adv.created_by.username) if adv.created_by else '—',
        } for adv in frank_advances_qs]

        frank_unpaid = Commission.objects.filter(
            barber=frank, is_paid=False, sale__approval_status='approved'
        ).aggregate(commissions=Sum('commission_amount'), tips=Sum('tip_amount'))

        if ledger['balance'] != 0 or frank_history or frank_advances:
            data.append({
                'barber_id': frank.id,
                'barber_name': frank.display_name,
                'is_frank': True,
                'total_commissions': float(frank_unpaid['commissions'] or 0),
                'total_tips': float(frank_unpaid['tips'] or 0),
                'total_earnings': float(ledger['unpaid_earnings']),
                'total_advances': float(ledger['unsettled_advances']),
                'net_payable': float(ledger['balance']),
                'history': frank_history,
                'advances': frank_advances,
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
    # Frank es la excepción: su saldo corriente puede quedar negativo (la deuda
    # se arrastra y se descuenta en los cierres siguientes), así que no se le
    # aplica el tope.
    if not barber.is_frank:
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

    Deja constancia en un `BarberPayment` (con `daily_close` nulo, que es lo que
    lo distingue del pago automático de Frank) y enlaza a él las comisiones y
    vales que cubrió, para que un superadmin pueda revertir exactamente este
    pago sin tocar liquidaciones anteriores (ver delete_barber_payment_view).
    """
    from apps.cashflow.models import Commission, BarberAdvance, BarberPayment
    from apps.barbers.models import Barber
    from django.utils import timezone
    from django.db import transaction
    from django.db.models import Sum
    from decimal import Decimal

    try:
        barber = Barber.objects.get(id=barber_id)
    except Barber.DoesNotExist:
        return Response({'error': 'Barbero no encontrado'}, status=404)

    # El pago de Frank se automatiza en el cierre diario ("Pago Diario: Franko").
    # Liquidarlo también por aquí lo pagaría dos veces.
    if 'frank' in (barber.display_name or '').lower():
        return Response(
            {'error': 'El pago de Frank se automatiza en el cierre diario; no se liquida desde aquí.'},
            status=400,
        )

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

        # El pago se crea ANTES de los updates: las comisiones y vales lo
        # referencian, y los querysets filtran por is_paid/is_settled, así que
        # marcarlos primero los vaciaría antes de poder enlazarlos.
        payment = BarberPayment.objects.create(
            barber=barber,
            daily_close=None,
            amount=net_amount,
            suggested_amount=net_amount,
            created_by=request.user,
            notes=f'Liquidación manual (acumulado ${earnings:,.0f}, vales ${total_advances:,.0f})',
        )

        unpaid.update(is_paid=True, paid_at=now, paid_in_payment=payment)
        advances.update(is_settled=True, settled_at=now, settled_in_payment=payment)

        msg = f"Liquidó a {barber.display_name}: ${net_amount:,.0f} neto (acumulado ${earnings:,.0f}"
        if total_advances > 0:
            msg += f" − vales ${total_advances:,.0f}"
        msg += f") — pago #{payment.id}"
        log_audit(
            user=request.user,
            action='payment',
            obj=payment,
            changes={'is_paid': True},
            request=request,
            extra_data={'msg': msg}
        )

    return Response({
        'ok': True,
        'message': f'Liquidación de ${net_amount:,.0f} netos registrada para {barber.display_name} (acumulado ${earnings:,.0f}, vales ${total_advances:,.0f}).'
    })


@api_view(['DELETE'])
@permission_classes([IsSuperAdmin])
def delete_barber_payment_view(request, payment_id):
    """DELETE /api/admin/cashflow/barber-payments/payment/<id>/delete/ - Anula una liquidación.

    Solo superadmin (Camilo / Juan David): sirve para corregir un pago
    registrado de más. Revierte exactamente lo que este pago liquidó —las
    comisiones y vales que lo referencian— y vuelve a dejar el saldo pendiente.

    El pago de Frank NO se anula por aquí: nace del cierre diario y su reverso
    correcto (que además devuelve el egreso y el efectivo) es eliminar el cierre.
    """
    from apps.cashflow.models import BarberPayment
    from django.db import transaction

    try:
        payment = BarberPayment.objects.select_related(
            'barber', 'daily_close'
        ).get(pk=payment_id)
    except BarberPayment.DoesNotExist:
        return Response({'error': 'Pago no encontrado'}, status=404)

    if payment.daily_close_id is not None:
        fecha = payment.daily_close.date.strftime('%Y-%m-%d')
        return Response({
            'error': f'Este pago se generó en el cierre diario del {fecha}. '
                     f'Para anularlo elimina ese cierre, así también se revierten '
                     f'el egreso y el efectivo del día.'
        }, status=400)

    barber_name = payment.barber.display_name if payment.barber else '?'
    amount = float(payment.amount)

    with transaction.atomic():
        # Revertir solo lo que ESTE pago cubrió. Las liquidaciones anteriores
        # apuntan a otros BarberPayment y no se tocan.
        commissions_reverted = payment.commissions.update(
            is_paid=False, paid_at=None, paid_in_payment=None
        )
        advances_reverted = payment.settled_advances.update(
            is_settled=False, settled_at=None, settled_in_payment=None
        )

        log_audit(
            user=request.user,
            action='delete',
            obj=None,
            changes={},
            request=request,
            extra_data={'msg': (
                f"Eliminó el pago #{payment.id} de ${amount:,.0f} a {barber_name} "
                f"({commissions_reverted} comisiones y {advances_reverted} vales "
                f"vuelven a quedar pendientes)"
            )}
        )
        payment.delete()

    return Response({
        'ok': True,
        'message': (
            f'Pago de ${amount:,.0f} a {barber_name} eliminado. '
            f'{commissions_reverted} comisiones y {advances_reverted} vales '
            f'volvieron a quedar pendientes.'
        )
    })


@api_view(['GET'])
@permission_classes([IsOperationalAdminOrAbove])
def barber_payment_detail_view(request, barber_id):
    """GET /api/admin/cashflow/barber-payments/<id>/detail/ - Desglose del saldo de un barbero.

    Responde "¿de qué está compuesto este pago?": los servicios uno por uno
    (cliente, servicio, hora, base, % y comisión), los vales que se restan y
    los pagos ya hechos. La tarjeta de la pantalla solo muestra los totales.
    """
    from apps.cashflow.models import Commission, BarberAdvance, BarberPayment, Sale
    from apps.barbers.models import Barber
    from django.utils import timezone

    try:
        barber = Barber.objects.get(id=barber_id)
    except Barber.DoesNotExist:
        return Response({'error': 'Barbero no encontrado'}, status=404)

    is_frank = 'frank' in (barber.display_name or '').lower()
    profile = getattr(request.user, 'profile', None)
    is_superadmin = bool(profile and profile.is_superadmin)

    # Servicios que componen el acumulado pendiente. Para Frank, `is_paid`
    # significa "ya procesada por un cierre", así que este listado es igualmente
    # lo que aún no ha entrado a ningún cierre.
    commissions = Commission.objects.filter(
        barber=barber, is_paid=False, sale__approval_status=Sale.STATUS_APPROVED
    ).select_related('sale', 'sale__booking', 'sale__service', 'sale__payment_method').order_by('-created_at')

    services = []
    for c in commissions:
        sale = c.sale
        created = timezone.localtime(c.created_at)
        services.append({
            'sale_id': sale.id,
            'date': created.strftime('%Y-%m-%d'),
            'time': created.strftime('%I:%M %p'),
            'client_name': sale.booking.client_name if sale.booking else 'N/A',
            'service_name': sale.service.name if sale.service else 'General',
            'base_price': float(sale.base_price),
            'final_price': float(sale.final_price),
            'basis_amount': float(c.basis_amount),
            'percentage': float(c.percentage),
            'commission_amount': float(c.commission_amount),
            'tip_amount': float(c.tip_amount),
            'total_earnings': float(c.total_earnings),
            'payment_method': sale.payment_method.name if sale.payment_method else '—',
        })

    advances_qs = BarberAdvance.objects.filter(
        barber=barber, is_settled=False
    ).select_related('created_by').order_by('-created_at')
    advances = [{
        'id': a.id,
        'amount': float(a.amount),
        'reason': a.reason,
        'date': timezone.localtime(a.created_at).strftime('%Y-%m-%d'),
        'by': (a.created_by.get_full_name() or a.created_by.username) if a.created_by else '—',
    } for a in advances_qs]

    # Pagos ya realizados. Los que nacieron de un cierre solo se revierten
    # borrando ese cierre, por eso no son borrables desde aquí.
    payments_qs = BarberPayment.objects.filter(
        barber=barber
    ).select_related('created_by', 'daily_close').order_by('-created_at')[:50]
    payments = [{
        'id': p.id,
        'amount': float(p.amount),
        'suggested_amount': float(p.suggested_amount),
        'date': timezone.localtime(p.created_at).strftime('%Y-%m-%d %I:%M %p'),
        'by': (p.created_by.get_full_name() or p.created_by.username) if p.created_by else '—',
        'notes': p.notes,
        'from_daily_close': p.daily_close_id is not None,
        'daily_close_date': p.daily_close.date.strftime('%Y-%m-%d') if p.daily_close else None,
        'can_delete': is_superadmin and p.daily_close_id is None,
    } for p in payments_qs]

    totals = {
        'commissions': sum(s['commission_amount'] for s in services),
        'tips': sum(s['tip_amount'] for s in services),
        'earnings': sum(s['total_earnings'] for s in services),
        'advances': sum(a['amount'] for a in advances),
        'services_count': len(services),
    }
    totals['net_payable'] = totals['earnings'] - totals['advances']

    data = {
        'barber_id': barber.id,
        'barber_name': barber.display_name,
        'is_frank': is_frank,
        'is_superadmin': is_superadmin,
        'services': services,
        'advances': advances,
        'payments': payments,
        'totals': totals,
    }

    # El saldo de Frank es el del ledger (arrastra días anteriores), no la suma
    # de lo pendiente. Mostrar otra cosa aquí contradiría su tarjeta.
    if is_frank:
        ledger = cashflow_services.compute_frank_ledger()
        data['ledger'] = {
            'earnings_total': float(ledger['earnings_total']),
            'advances_total': float(ledger['advances_total']),
            'payments_total': float(ledger['payments_total']),
            'balance': float(ledger['balance']),
        }

    return Response(data)


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
