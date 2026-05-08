from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from decimal import Decimal
from django.utils import timezone

from apps.cashflow.models import Commission, DailyClose, Expense, Sale
from apps.barbers.models import Barber

class Command(BaseCommand):
    help = 'Corrige el historial de cierres: ajusta las comisiones de Franko al 50% y mueve su pago a egresos en la historia.'

    def handle(self, *args, **options):
        frank = Barber.objects.filter(display_name__icontains='frank').first()
        if not frank:
            frank = Barber.objects.filter(user__first_name__icontains='frank').first()
            
        if not frank:
            self.stdout.write(self.style.ERROR('No se encontró al barbero Franko.'))
            return

        with transaction.atomic():
            # 1. Ajustar todas las comisiones de Franko al 50%
            frank_commissions = Commission.objects.filter(barber=frank)
            updated_comms = 0
            for comm in frank_commissions:
                # Si no estaba ya al 50% o queremos forzar el recálculo
                comm.percentage = Decimal('50.00')
                comm.commission_amount = (comm.basis_amount * comm.percentage) / Decimal('100.00')
                comm.total_earnings = comm.commission_amount + comm.tip_amount
                comm.save(update_fields=['percentage', 'commission_amount', 'total_earnings'])
                updated_comms += 1
                
            self.stdout.write(self.style.SUCCESS(f'Actualizadas {updated_comms} comisiones de Franko al 50%.'))

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
                        expense.amount = frank_pay
                        expense.save(update_fields=['amount'])
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
                    # Si resulta que no hubo pago, eliminar egreso
                    expense.delete()
                
                # Recalcular totales del cierre
                total_expenses = close.expenses.aggregate(total=Sum('amount'))['total'] or 0
                total_sales = sales.aggregate(total=Sum('final_price'))['total'] or 0
                total_tips = sales.aggregate(total=Sum('tip_amount'))['total'] or 0
                total_inventory = close.inventory_sales.aggregate(total=Sum('total_price'))['total'] or 0
                
                # Neto = (Ventas) + (Inventario) - (Comisiones de otros) - (Gastos, incluido Frank)
                net_income = total_sales + total_inventory - total_other_comms - total_expenses
                
                close.total_sales = total_sales
                close.total_tips = total_tips
                close.total_commissions = total_other_comms
                close.total_expenses = total_expenses
                close.net_income = net_income
                close.save(update_fields=['total_sales', 'total_tips', 'total_commissions', 'total_expenses', 'net_income'])
                
                updated_closes += 1

            self.stdout.write(self.style.SUCCESS(f'Actualizados {updated_closes} cierres de caja.'))
