"""Convierte un egreso mal registrado en un vale de verdad.

El caso (ver PLAN_CONCILIACION_CAJA.md, decisión D3): cuando un adelanto a un
barbero se escribe como egreso suelto ("Vale Franko"), la plata sale de la caja
pero no baja el acumulado del barbero. El cierre le sigue sugiriendo pagarle
completo, así que termina recibiendo dos veces lo mismo.

Este comando toma ese egreso y lo vuelve un `BarberAdvance`:

  - conserva el monto, la fuente (efectivo / transferencia) y quién lo registró;
  - le copia la fecha de registro original, para que caiga en el mismo período
    de caja y el "Debe haber" no se mueva ni un peso;
  - borra el egreso.

El efecto neto sobre la caja es CERO: sale un egreso en efectivo, entra un vale
en efectivo. Lo que cambia es el saldo del barbero, que por fin baja.

Se corre uno por uno y solo con la lista que apruebe el dueño — nunca en masa:
un egreso puede decir "vale" sin ser un adelanto.

    python manage.py convert_expense_to_advance --expense-id 123 --barber-id 4
    python manage.py convert_expense_to_advance --expense-id 123 --barber-id 4 --apply

Sin `--apply` solo simula.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.barbers.models import Barber
from apps.cashflow.models import BarberAdvance, Expense


class Command(BaseCommand):
    help = 'Convierte un egreso mal registrado en un vale/adelanto de barbero.'

    def add_arguments(self, parser):
        parser.add_argument('--expense-id', type=int, required=True,
                            help='Id del egreso a convertir.')
        parser.add_argument('--barber-id', type=int, required=True,
                            help='Id del barbero que recibió el adelanto.')
        parser.add_argument('--apply', action='store_true',
                            help='Escribe los cambios. Sin esta bandera solo simula.')

    def handle(self, *args, **options):
        try:
            expense = Expense.objects.select_related(
                'registered_by', 'included_in_daily_close'
            ).get(pk=options['expense_id'])
        except Expense.DoesNotExist:
            raise CommandError(f"No existe el egreso #{options['expense_id']}.")

        try:
            barber = Barber.objects.get(pk=options['barber_id'])
        except Barber.DoesNotExist:
            raise CommandError(f"No existe el barbero #{options['barber_id']}.")

        if expense.payment_source not in ('cash', 'transfer'):
            raise CommandError(
                f"El egreso #{expense.id} tiene fuente '{expense.payment_source}': "
                'no salió de la caja, así que no corresponde a un vale.'
            )

        fuente = 'Efectivo' if expense.payment_source == 'cash' else 'Transferencia'

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('CONVERSIÓN DE EGRESO A VALE'))
        self.stdout.write(f'  Egreso   #{expense.id}  "{expense.description}"')
        self.stdout.write(f'  Monto    ${Decimal(expense.amount):,.0f}  ({fuente})')
        self.stdout.write(f'  Fecha    {expense.date} · registrado {expense.created_at}')
        self.stdout.write(f'  Barbero  {barber.display_name} (#{barber.id})')
        self.stdout.write('')
        self.stdout.write('  Efecto sobre la caja: ninguno (sale un egreso, entra un vale).')
        self.stdout.write(
            f'  Efecto sobre el saldo de {barber.display_name}: '
            f'baja ${Decimal(expense.amount):,.0f}.'
        )

        if expense.included_in_daily_close_id:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'  OJO: el egreso está dentro del cierre #{expense.included_in_daily_close_id} '
                f'({expense.included_in_daily_close.date}). Ese cierre ya está sellado: '
                'su total_expenses conserva el valor histórico y NO se recalcula.'
            ))

        if not options['apply']:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                '  SIMULACIÓN. Nada se escribió. Agrega --apply para ejecutarlo.'))
            return

        with transaction.atomic():
            advance = BarberAdvance.objects.create(
                barber=barber,
                amount=expense.amount,
                reason=f'Convertido del egreso #{expense.id}: {expense.description}'[:255],
                payment_source=expense.payment_source,
                created_by=expense.registered_by,
            )
            # `created_at` es auto_now_add: solo se puede fijar con update().
            # Importa porque el período de caja se acota por esa fecha.
            BarberAdvance.objects.filter(pk=advance.pk).update(
                created_at=expense.created_at)

            descripcion = expense.description
            monto = Decimal(expense.amount)
            expense.delete()

        # El log de auditoría deja el rastro de quién hizo el arreglo y sobre qué.
        try:
            from apps.analytics.models import log_audit
            log_audit(
                user=None,
                action='update',
                obj=advance,
                changes={'de_egreso': options['expense_id'], 'monto': float(monto)},
                extra_data={'msg': (
                    f'Convirtió el egreso "{descripcion}" (${monto:,.0f}) en un vale '
                    f'de {barber.display_name}, vía convert_expense_to_advance.'
                )},
            )
        except Exception:
            # El arreglo ya se aplicó; que falle la bitácora no debe deshacerlo.
            self.stdout.write(self.style.WARNING(
                '  (no se pudo escribir en el log de auditoría)'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'  LISTO. Vale #{advance.id} creado para {barber.display_name} '
            f'y egreso #{options["expense_id"]} eliminado.'))
        self.stdout.write('')
