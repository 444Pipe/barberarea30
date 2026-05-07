"""
cashflow/services.py
====================
Capa de lógica de negocio para el Checkout.

Centraliza la transacción completa de una venta:
  1. Crear Sale (Venta)
  2. Calcular y guardar Commission
  3. Descontar Inventario (InventoryMovement)
  4. Marcar Booking como completada
  5. Registrar en AuditLog (inmutable)

Toda la operación corre dentro de un bloque transaction.atomic(),
garantizando que o todo sucede o nada sucede (rollback automático).
"""
from django.db import transaction
from django.utils import timezone

from apps.cashflow.models import Sale, Commission, PaymentMethod
from apps.inventory.models import ServiceInventoryItem, InventoryMovement
from apps.analytics.models import log_audit


def process_checkout(*, booking, confirmed_by, payment_method_id=None,
                     payment_reference='', tip_amount=0,
                     discount_amount=0, discount_assumed_by='none',
                     added_value_amount=0, added_value_description='',
                     commission_percentage=50, notes='', 
                     frank_materials_cost=0, frank_labor_cost=0,
                     request=None):
    """
    Procesa el checkout completo de una reserva de forma atómica.
    """
    from decimal import Decimal
    from apps.cashflow.models import Expense

    if booking.status in ('completed', 'cancelled'):
        raise ValueError(
            f'La reserva #{booking.id} ya está en estado "{booking.status}" '
            'y no puede procesarse de nuevo.'
        )

    with transaction.atomic():
        # ── 1. Método de pago ───────────────────────────────────────────
        payment_method = None
        if payment_method_id:
            payment_method = PaymentMethod.objects.filter(id=payment_method_id).first()

        # ── 2. Crear Venta ──────────────────────────────────────────────
        user_profile = getattr(confirmed_by, 'profile', None)
        if user_profile and user_profile.role in ('operational_admin', 'superadmin', 'admin'):
            approval_status = Sale.STATUS_APPROVED
        else:
            approval_status = Sale.STATUS_PENDING

        # Si viene con costos de materiales (Ej. servicio manual de Frank)
        base_price = booking.price
        if frank_materials_cost > 0 or frank_labor_cost > 0:
            base_price = Decimal(str(frank_materials_cost)) + Decimal(str(frank_labor_cost))

        sale = Sale.objects.create(
            booking=booking,
            barber=booking.barber,
            service=booking.service,
            base_price=base_price,
            added_value_amount=added_value_amount,
            added_value_description=added_value_description,
            discount_amount=discount_amount,
            discount_assumed_by=discount_assumed_by,
            tip_amount=tip_amount,
            payment_method=payment_method,
            payment_reference=payment_reference,
            confirmed_by=confirmed_by,
            notes=notes,
            approval_status=approval_status,
        )

        # ── 3. Comisión y Gastos Especiales ─────────────────────────────
        if booking.barber:
            comm = Commission.objects.create(
                sale=sale,
                barber=booking.barber,
                percentage=commission_percentage,
            )
            
            # Si hay materiales separados, ajustamos la comisión y creamos el gasto
            if frank_materials_cost > 0:
                labor_val = Decimal(str(frank_labor_cost))
                percentage_dec = Decimal(str(commission_percentage)) / Decimal('100.00')
                new_comm_amt = labor_val * percentage_dec
                new_total = new_comm_amt + sale.tip_amount
                
                # Actualizamos directo en la BD para saltarnos el método save()
                Commission.objects.filter(id=comm.id).update(
                    basis_amount=labor_val,
                    commission_amount=new_comm_amt,
                    total_earnings=new_total
                )
                
                # Crear Egreso para los materiales
                Expense.objects.create(
                    description=f"Materiales Servicio: {booking.client_name}",
                    amount=Decimal(str(frank_materials_cost)),
                    expense_type='variable',
                    registered_by=confirmed_by
                )

        # ── 4. Descuento de Inventario ─────────────────────────────────
        if booking.service:
            for req in ServiceInventoryItem.objects.filter(service=booking.service):
                item = req.item
                qty_before = item.quantity
                item.quantity -= req.quantity_per_service
                # Nunca dejar en negativo — registra y alerta, pero no bloquea
                if item.quantity < 0:
                    item.quantity = 0
                item.save()

                InventoryMovement.objects.create(
                    item=item,
                    movement_type='out',
                    quantity=req.quantity_per_service,
                    quantity_before=qty_before,
                    quantity_after=item.quantity,
                    booking=booking,
                    performed_by=confirmed_by,
                    notes=f'Consumo automático por servicio "{booking.service.name}"',
                )

        # ── 5. Actualizar estado de la Reserva ─────────────────────────
        booking.status = 'completed'
        booking.completed_at = timezone.now()
        booking.price = sale.final_price
        booking.save(update_fields=['status', 'completed_at', 'price'])

        # ── 6. Registro de Auditoría ────────────────────────────────────
        log_audit(
            user=confirmed_by,
            action='payment',
            obj=sale,
            changes={
                'base_price': str(sale.base_price),
                'discount': str(sale.discount_amount),
                'discount_assumed_by': sale.discount_assumed_by,
                'final_price': str(sale.final_price),
                'tip': str(sale.tip_amount),
                'total_paid': str(sale.total_paid),
                'payment_method': payment_method.name if payment_method else 'Sin especificar',
                'payment_reference': payment_reference,
            },
            request=request,
            extra_data={
                'msg': (
                    f'Checkout de {booking.client_name} por ${sale.total_paid:,.0f} '
                    f'— Barbero: {booking.barber.display_name if booking.barber else "N/A"}'
                )
            },
        )

    return sale
