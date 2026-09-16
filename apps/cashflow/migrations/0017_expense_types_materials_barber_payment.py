"""Separa 'Materiales' y 'Pago a barberos' del cajón de sastre 'variable'.

Hasta ahora los tres vivían bajo el mismo tipo y la única forma de
distinguirlos era leer el prefijo de la descripción. El dueño necesita el
desglose ("cuánto en materiales, cuánto en el día a día, cuánto en barberos") y
el ROI necesita un criterio que no dependa de un texto editable.

El backfill reclasifica el historial por ese mismo prefijo, una sola vez. Es
idempotente: se puede correr de nuevo sin efecto (`seed.py` lo repite en cada
arranque como red de seguridad, porque el historial de migraciones en Railway
ha fallado antes).
"""

from django.db import migrations, models


# Los prefijos que el sistema ha usado siempre para sus egresos automáticos.
# Se replican como literales, no se importan de services.py: una migración debe
# seguir corriendo igual aunque ese módulo cambie mañana.
MATERIALS_PREFIX = 'Materiales Servicio:'
FRANK_DAILY_PREFIX = 'Pago Diario: Franko'


def reclasificar(apps, schema_editor):
    Expense = apps.get_model('cashflow', 'Expense')

    materiales = (
        Expense.objects
        .filter(description__startswith=MATERIALS_PREFIX)
        .exclude(expense_type='materials')
        .update(expense_type='materials')
    )
    pagos = (
        Expense.objects
        .filter(description__startswith=FRANK_DAILY_PREFIX)
        .exclude(expense_type='barber_payment')
        .update(expense_type='barber_payment')
    )
    if materiales or pagos:
        print(f'  Reclasificados: {materiales} a materials, {pagos} a barber_payment.')


def revertir(apps, schema_editor):
    """Devuelve los dos tipos nuevos a 'variable', que es de donde salieron."""
    Expense = apps.get_model('cashflow', 'Expense')
    Expense.objects.filter(
        expense_type__in=['materials', 'barber_payment']
    ).update(expense_type='variable')


class Migration(migrations.Migration):

    dependencies = [
        ('cashflow', '0016_expense_payment_source_none'),
    ]

    operations = [
        migrations.AlterField(
            model_name='expense',
            name='expense_type',
            field=models.CharField(
                choices=[
                    ('fixed', 'Fijo (Arriendo, Servicios, Nómina)'),
                    ('variable', 'Variable (Día a día)'),
                    ('inventory', 'Compra de Inventario'),
                    ('materials', 'Materiales / insumos de servicio'),
                    ('barber_payment', 'Pago a barberos'),
                ],
                default='variable',
                max_length=20,
            ),
        ),
        migrations.RunPython(reclasificar, revertir),
    ]
