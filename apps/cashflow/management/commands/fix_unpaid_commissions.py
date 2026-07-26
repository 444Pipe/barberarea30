"""Recalcula las comisiones NO pagadas de un barbero a su porcentaje correcto.

Caso que lo motiva: la migración `barbers.0010` puso a todos los barberos en
40% (incluido Frank, cuyo acuerdo es 50%) y la corrección del perfil llegó dos
meses después. Las comisiones emitidas en el medio quedaron congeladas al 40%,
porque `Commission.percentage` se copia en el checkout y no se recalcula al
cambiar el perfil.

Por seguridad NO escribe nada sin `--apply`: sin esa bandera solo simula.

    python manage.py fix_unpaid_commissions --barber frank
    python manage.py fix_unpaid_commissions --barber frank --apply
"""

from django.core.management.base import BaseCommand, CommandError

from apps.barbers.models import Barber
from apps.cashflow import services as cashflow_services


class Command(BaseCommand):
    help = 'Recalcula las comisiones no pagadas de un barbero al porcentaje de su perfil.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--barber', required=True,
            help='Nombre (o parte) del barbero. Ej: frank',
        )
        parser.add_argument(
            '--percentage', type=float, default=None,
            help='Porcentaje objetivo. Por defecto, el del perfil del barbero.',
        )
        parser.add_argument(
            '--apply', action='store_true',
            help='Escribe los cambios. Sin esta bandera solo simula.',
        )

    def handle(self, *args, **options):
        matches = Barber.objects.filter(display_name__icontains=options['barber'])
        if not matches.exists():
            raise CommandError(f'No hay barberos que coincidan con "{options["barber"]}".')
        if matches.count() > 1:
            nombres = ', '.join(matches.values_list('display_name', flat=True))
            raise CommandError(f'"{options["barber"]}" coincide con varios barberos: {nombres}.')

        barber = matches.first()
        percentage = options['percentage']
        if percentage is None:
            percentage = barber.commission_percentage

        result = cashflow_services.recalculate_unpaid_commissions(
            barber=barber, new_percentage=percentage, apply=options['apply'],
        )

        if result['count'] == 0:
            self.stdout.write(self.style.SUCCESS(
                f'{barber.display_name}: no hay comisiones pendientes por debajo '
                f'del {result["new_percentage"]:.0f}%. Nada que corregir.'
            ))
            return

        self.stdout.write(
            f'{barber.display_name} — {result["count"]} comisión/es no pagada/s '
            f'se llevarían al {result["new_percentage"]:.0f}%:'
        )
        for row in result['rows']:
            self.stdout.write(
                f'  #{row["id"]:<6} {row["date"]}  {row["service"][:28]:<28} '
                f'base ${row["basis_amount"]:>10,.0f}  '
                f'{row["old_percentage"]:.0f}% → {result["new_percentage"]:.0f}%  '
                f'${row["old_commission"]:>9,.0f} → ${row["new_commission"]:>9,.0f}'
            )
        self.stdout.write(
            f'\nGanancias pendientes: ${result["earnings_before"]:,.0f} → '
            f'${result["earnings_after"]:,.0f}  '
            f'(diferencia a favor del barbero: ${result["difference"]:,.0f})'
        )

        if result['applied']:
            self.stdout.write(self.style.SUCCESS('\n✓ Cambios aplicados.'))
        else:
            self.stdout.write(self.style.WARNING(
                '\nSIMULACIÓN — no se escribió nada. Repite con --apply para aplicarlo.'
            ))
