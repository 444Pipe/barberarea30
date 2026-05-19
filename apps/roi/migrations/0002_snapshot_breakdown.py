"""
Migración 0002 — Desglose financiero del MonthlyROISnapshot.

Añade los campos:
  • gross_services             (Decimal 15,0)  — ingresos por servicios
  • total_inventory_sales      (Decimal 15,0)  — ingresos por inventario
  • total_fixed_expenses       (Decimal 15,0)  — egresos fijos (arriendo, etc.)
  • total_operational_expenses (Decimal 15,0)  — egresos operativos (variables + inventario)

`gross_income`, `total_expenses` y `net_income` siguen existiendo y
ahora se calculan como sumatorias de los desgloses.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('roi', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='monthlyroisnapshot',
            name='gross_services',
            field=models.DecimalField(
                decimal_places=0, default=0,
                help_text='Suma de Sale.final_price de ventas aprobadas del mes.',
                max_digits=15,
                verbose_name='Ingresos por Servicios',
            ),
        ),
        migrations.AddField(
            model_name='monthlyroisnapshot',
            name='total_inventory_sales',
            field=models.DecimalField(
                decimal_places=0, default=0,
                help_text='Suma de InventorySale.total_price del mes.',
                max_digits=15,
                verbose_name='Ingresos por Venta de Inventario',
            ),
        ),
        migrations.AddField(
            model_name='monthlyroisnapshot',
            name='total_fixed_expenses',
            field=models.DecimalField(
                decimal_places=0, default=0,
                help_text='Expense.amount donde expense_type=fixed.',
                max_digits=15,
                verbose_name='Egresos Fijos (Arriendo, Servicios, Nómina)',
            ),
        ),
        migrations.AddField(
            model_name='monthlyroisnapshot',
            name='total_operational_expenses',
            field=models.DecimalField(
                decimal_places=0, default=0,
                help_text='Expense.amount donde expense_type IN (variable, inventory), '
                          'excluyendo "Pago Diario: Franko" (ya está en comisiones).',
                max_digits=15,
                verbose_name='Egresos Operativos (Variables + Inventario)',
            ),
        ),
        # Mejor texto de ayuda en los campos ya existentes
        migrations.AlterField(
            model_name='monthlyroisnapshot',
            name='gross_income',
            field=models.DecimalField(
                decimal_places=0, default=0,
                help_text='gross_services + total_inventory_sales',
                max_digits=15,
                verbose_name='Ingresos Brutos (Servicios + Inventario)',
            ),
        ),
        migrations.AlterField(
            model_name='monthlyroisnapshot',
            name='total_expenses',
            field=models.DecimalField(
                decimal_places=0, default=0,
                max_digits=15,
                verbose_name='Total Egresos (Fijos + Operativos)',
            ),
        ),
        migrations.AlterField(
            model_name='monthlyroisnapshot',
            name='net_income',
            field=models.DecimalField(
                decimal_places=0, default=0,
                help_text='gross_income - total_commissions - total_fixed_expenses - total_operational_expenses',
                max_digits=15,
                verbose_name='Ganancia Neta del Mes',
            ),
        ),
        migrations.AlterField(
            model_name='monthlyroisnapshot',
            name='total_commissions',
            field=models.DecimalField(
                decimal_places=0, default=0,
                help_text='40% staff general / 50% Frank. Suma de Commission.commission_amount del mes.',
                max_digits=15,
                verbose_name='Total Comisiones Barberos',
            ),
        ),
    ]
