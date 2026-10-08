"""Lista reservas ACTIVAS que caen dentro de un bloqueo de inactividad.

Nace de un caso real (oct-2026): Frank estaba bloqueado hasta el 31-dic y
seguían apareciendo citas con él. Este comando dice cuáles son y POR QUÉ están
ahí. No borra ni cancela nada: decidir qué hacer con cada cliente es del negocio.

    python manage.py find_bookings_in_blocks                 # desde hoy, todos
    python manage.py find_bookings_in_blocks --barber frank
    python manage.py find_bookings_in_blocks --from 2026-01-01

Causas que reporta por cita:
  CREADA ANTES DEL BLOQUEO  → ya existía cuando se bloqueó al barbero.
  FORZADA (walk-in/manual)  → el personal la agendó encima, con confirmación.
  CREADA DESPUÉS (hueco)    → entró por un camino que no revisaba el bloqueo
                              (cerrados en oct-2026).
"""
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.barbers.models import Barber
from apps.bookings.validators import bookings_in_unavailability


class Command(BaseCommand):
    help = 'Lista reservas activas que caen dentro de un bloqueo de inactividad (no cambia nada).'

    def add_arguments(self, parser):
        parser.add_argument('--barber', default='', help='Filtra por nombre (icontains), ej: frank')
        parser.add_argument('--from', dest='date_from', default='',
                            help='Desde esta fecha (YYYY-MM-DD). Por defecto: hoy.')

    def handle(self, *args, **opts):
        date_from = timezone.localdate()
        if opts['date_from']:
            try:
                date_from = datetime.strptime(opts['date_from'], '%Y-%m-%d').date()
            except ValueError:
                self.stderr.write('Fecha --from inválida (usa YYYY-MM-DD).')
                return

        barbers = Barber.objects.all()
        if opts['barber']:
            barbers = barbers.filter(display_name__icontains=opts['barber'])

        total = 0
        for barber in barbers:
            hits = bookings_in_unavailability(barber=barber, date_from=date_from)
            if not hits:
                continue
            self.stdout.write(self.style.WARNING(
                f'\n{barber.display_name} (id {barber.id}): {len(hits)} cita(s) dentro de un bloqueo'
            ))
            for hit in hits:
                bk, u = hit['booking'], hit['block']
                if 'bloqueo de inactividad' in (bk.notes or ''):
                    cause = 'FORZADA (walk-in/manual)'
                elif bk.created_at < u.created_at:
                    cause = 'CREADA ANTES DEL BLOQUEO'
                else:
                    cause = 'CREADA DESPUÉS (hueco)'
                created = timezone.localtime(bk.created_at).strftime('%Y-%m-%d %H:%M')
                self.stdout.write(
                    f'  #{bk.id} {bk.date} {bk.time.strftime("%H:%M")} {bk.status:<9} '
                    f'{bk.client_name} ({bk.client_phone or "sin teléfono"}) '
                    f'walk_in={bk.is_walk_in} creada={created} '
                    f'bloqueo={u.start_time.strftime("%H:%M")}-{u.end_time.strftime("%H:%M")} '
                    f'-> {cause}'
                )
            total += len(hits)

        if total:
            self.stdout.write(self.style.WARNING(f'\nTotal: {total} cita(s) dentro de bloqueos.'))
        else:
            self.stdout.write(self.style.SUCCESS('No hay citas activas dentro de bloqueos.'))
