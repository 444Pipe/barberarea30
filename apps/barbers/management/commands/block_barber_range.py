"""Deja a un barbero SIN reservas web (bloqueo de día completo) en un rango.

Caso real (oct-2026): Frank tenía "bloqueado hasta el 31-dic" pero solo de 1 a
9 p.m., y las mañanas seguían abiertas en la web. Este comando lo deja con un
bloqueo de DÍA COMPLETO, todos los días del rango.

    # Ver qué haría (no cambia nada):
    python manage.py block_barber_range --barber frank --from 2026-10-08 --to 2026-12-31
    # Aplicar, reemplazando los bloqueos parciales que había en el rango:
    python manage.py block_barber_range --barber frank --from 2026-10-08 --to 2026-12-31 \\
        --reason "Sin reservas web hasta el 31-dic-2026" --replace --apply

No toca las citas que ya existen: las lista para que alguien llame al cliente.
Los walk-in del panel pueden seguir forzando encima, con confirmación.
"""
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.barbers.models import Barber, BarberUnavailability
from apps.bookings.models import Booking


class Command(BaseCommand):
    help = 'Bloquea a un barbero el día completo en un rango de fechas (sin reservas web).'

    def add_arguments(self, parser):
        parser.add_argument('--barber', required=True, help='Nombre del barbero (icontains), ej: frank')
        parser.add_argument('--from', dest='date_from', required=True, help='YYYY-MM-DD (incluido)')
        parser.add_argument('--to', dest='date_to', required=True, help='YYYY-MM-DD (incluido)')
        parser.add_argument('--reason', default='Sin reservas web', help='Motivo que se verá en el panel')
        parser.add_argument('--replace', action='store_true',
                            help='Borra los bloqueos que ya tenga en el rango antes de crear los nuevos')
        parser.add_argument('--apply', action='store_true', help='Aplicar (sin esto solo muestra)')

    def handle(self, *args, **opts):
        barbers = Barber.objects.filter(display_name__icontains=opts['barber'])
        if barbers.count() != 1:
            raise CommandError(f'--barber debe identificar a UN barbero (encontrados: {barbers.count()}).')
        barber = barbers.get()
        try:
            d0 = datetime.strptime(opts['date_from'], '%Y-%m-%d').date()
            d1 = datetime.strptime(opts['date_to'], '%Y-%m-%d').date()
        except ValueError:
            raise CommandError('Fechas inválidas (use YYYY-MM-DD).')
        if d1 < d0 or (d1 - d0).days > 400:
            raise CommandError('Rango inválido (máximo 400 días).')

        existing = BarberUnavailability.objects.filter(barber=barber, date__range=(d0, d1))
        days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
        apply = opts['apply']
        self.stdout.write(
            f'{"APLICANDO" if apply else "SIMULACIÓN (usa --apply)"}: {barber.display_name} (#{barber.id}) '
            f'sin reservas del {d0} al {d1} ({len(days)} días, día completo).'
        )
        self.stdout.write(f'  Bloqueos que ya tiene en el rango: {existing.count()}'
                          + (' (se reemplazan)' if opts['replace'] else ' (se conservan)'))

        with transaction.atomic():
            if apply and opts['replace']:
                existing.delete()
            covered = set()
            if not opts['replace']:
                covered = {
                    u.date for u in existing
                    if u.start_time <= time(0, 0) and u.end_time >= time(23, 59)
                }
            to_create = [
                BarberUnavailability(
                    barber=barber, date=d, start_time=time(0, 0),
                    end_time=time(23, 59, 59), reason=opts['reason'][:255],
                )
                for d in days if d not in covered
            ]
            if apply:
                BarberUnavailability.objects.bulk_create(to_create)
            self.stdout.write(f'  Bloqueos de día completo a crear: {len(to_create)}')

        active = Booking.objects.filter(
            barber=barber, date__range=(d0, d1), status__in=['pending', 'confirmed'],
        ).order_by('date', 'time')
        if active.exists():
            self.stdout.write(self.style.WARNING(
                f'  {active.count()} cita(s) activa(s) en el rango (NO se cancelan; hay que llamar al cliente):'
            ))
            for bk in active:
                self.stdout.write(f'    #{bk.id} {bk.date} {bk.time:%H:%M} {bk.status} {bk.client_name}')
        self.stdout.write(self.style.SUCCESS('Listo.') if apply
                          else self.style.WARNING('Simulación: no se cambió nada.'))
