"""Detecta reservas ACTIVAS que se solapan para un mismo barbero.

Nace de un caso real: antes del arreglo de `Barber.occupied_minutes` (24-jul),
Frank ocupaba solo la duración nominal del servicio y se colaban citas cada 30
min aunque él ocupa 2h. El sistema ya no crea solapes nuevos, pero pueden quedar
datos viejos así. Este comando los LISTA (no borra nada): la decisión de cuál
cita conservar es del negocio (ambas pueden ser clientes reales).

    python manage.py find_booking_overlaps            # todos los barberos
    python manage.py find_booking_overlaps --barber frank
"""
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

from apps.bookings.models import Booking
from apps.barbers.models import Barber


class Command(BaseCommand):
    help = 'Lista reservas activas que se solapan para un mismo barbero (no borra nada).'

    def add_arguments(self, parser):
        parser.add_argument('--barber', default='', help='Filtra por nombre (icontains), ej: frank')
        parser.add_argument('--from', dest='date_from', default='', help='Solo desde esta fecha (YYYY-MM-DD)')

    def handle(self, *args, **opts):
        barbers = Barber.objects.all()
        if opts['barber']:
            barbers = barbers.filter(display_name__icontains=opts['barber'])

        date_from = None
        if opts['date_from']:
            try:
                date_from = datetime.strptime(opts['date_from'], '%Y-%m-%d').date()
            except ValueError:
                self.stderr.write('Fecha --from inválida (usa YYYY-MM-DD).')
                return

        total = 0
        for barber in barbers:
            qs = Booking.objects.filter(
                barber=barber, status__in=['pending', 'confirmed']
            )
            if date_from:
                qs = qs.filter(date__gte=date_from)
            # Agrupar por fecha y detectar cruces reales usando la duración real
            # (occupied_minutes: 120 para Frank), no la guardada.
            by_date = {}
            for bk in qs.order_by('date', 'time'):
                by_date.setdefault(bk.date, []).append(bk)

            for date, day_bookings in by_date.items():
                for i, a in enumerate(day_bookings):
                    a_start = datetime.combine(date, a.time)
                    a_end = a_start + timedelta(minutes=barber.occupied_minutes(a.duration_minutes))
                    for b in day_bookings[i + 1:]:
                        b_start = datetime.combine(date, b.time)
                        b_end = b_start + timedelta(minutes=barber.occupied_minutes(b.duration_minutes))
                        if a_start < b_end and a_end > b_start:
                            total += 1
                            self.stdout.write(self.style.WARNING(
                                f'SOLAPE - {barber.display_name} - {date}: '
                                f'#{a.id} {a.time.strftime("%I:%M %p")} ({a.client_name}) '
                                f'x #{b.id} {b.time.strftime("%I:%M %p")} ({b.client_name})'
                            ))

        if total == 0:
            self.stdout.write(self.style.SUCCESS('Sin solapes activos. Todo en orden.'))
        else:
            self.stdout.write(self.style.ERROR(
                f'\n{total} solape(s) encontrado(s). Revisa cada par en el panel y '
                f'cancela/reagenda la cita que corresponda (ambas pueden ser reales).'
            ))
