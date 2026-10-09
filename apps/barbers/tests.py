"""Tests de disponibilidad del barbero: modo "horario a elección" y bloqueo por rango."""
from datetime import time, timedelta
from decimal import Decimal
from importlib import import_module
from io import StringIO
from unittest import mock

from django.apps import apps as global_apps
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.barbers.models import Barber, BarberUnavailability, BarberWorkHours
from apps.bookings.holidays import is_holiday
from apps.bookings.models import Booking
from apps.services.models import Service
from apps.users.models import Barbershop, UserProfile


def _next_working_wednesday():
    d = timezone.localdate() + timedelta(days=7)
    while d.weekday() != 2 or is_holiday(d):
        d += timedelta(days=1)
    return d


@mock.patch('threading.Thread')
class CustomHoursModeTests(TestCase):
    """Cristian: no recibe reservas salvo en las franjas que él abre."""

    def setUp(self):
        shop = Barbershop.objects.create(name='Área 30 Test')
        self.user = User.objects.create_user('cristian.admin', password='x')
        UserProfile.objects.create(user=self.user, role='superadmin', barbershop=shop)
        self.barber = Barber.objects.create(
            user=self.user, barbershop=shop, display_name='Cristian', only_custom_hours=True,
        )
        self.svc = Service.objects.create(name='Corte', slug='corte-c', price=Decimal('30000'))
        self.day = _next_working_wednesday()

    def _public(self, t):
        return self.client.post('/api/bookings/', {
            'client_name': 'Cliente', 'client_phone': '3001234567', 'service_id': self.svc.id,
            'barber_id': self.barber.id, 'date': self.day.isoformat(), 'time': t,
            'privacy_accepted': True,
        }, content_type='application/json')

    def test_sin_franja_abierta_no_atiende(self, _thread):
        self.assertIsNone(self.barber.day_window(self.day))
        r = self.client.get(f'/api/barbers/{self.barber.id}/availability/?date={self.day}')
        self.assertTrue(r.json()['day_off'])
        r = self._public('15:00')
        self.assertEqual(r.status_code, 409)
        self.assertIn('no tiene horario abierto', r.json()['error'])

    def test_con_franja_abierta_atiende_solo_ahi(self, _thread):
        BarberWorkHours.objects.create(
            barber=self.barber, date_from=self.day, date_to=self.day,
            start_time=time(15, 0), end_time=time(18, 0),
        )
        w = self.barber.day_window(self.day)
        self.assertEqual((w['start'], w['end']), (time(15, 0), time(18, 0)))
        self.assertEqual(self._public('15:00').status_code, 201)
        self.assertEqual(self._public('11:00').status_code, 409)

    def test_el_interruptor_cambia_el_modo(self, _thread):
        self.client.force_login(self.user)
        url = f'/api/admin/barbers/{self.barber.id}/work-hours/mode/'
        r = self.client.post(url, {'only_custom_hours': False}, content_type='application/json')
        self.assertFalse(r.json()['only_custom_hours'])
        self.barber.refresh_from_db()
        self.assertEqual(self.barber.day_window(self.day)['end'], time(20, 0))

    def test_migracion_pasa_a_cristian_al_modo_y_limpia_sus_bloqueos(self, _thread):
        Barber.objects.filter(pk=self.barber.pk).update(only_custom_hours=False)
        today = timezone.localdate()
        past = BarberUnavailability.objects.create(
            barber=self.barber, date=today - timedelta(days=3),
            start_time=time(0, 0), end_time=time(23, 59, 59))
        with_reason = BarberUnavailability.objects.create(
            barber=self.barber, date=today + timedelta(days=2),
            start_time=time(0, 0), end_time=time(23, 59, 59), reason='Viaje')
        for i in range(5):
            BarberUnavailability.objects.create(
                barber=self.barber, date=today + timedelta(days=i),
                start_time=time(0, 0), end_time=time(23, 59, 59))
        mig = import_module('apps.barbers.migrations.0016_cristian_custom_hours_mode')
        mig.forwards(global_apps, None)
        self.barber.refresh_from_db()
        self.assertTrue(self.barber.only_custom_hours)
        left = set(BarberUnavailability.objects.filter(barber=self.barber).values_list('pk', flat=True))
        self.assertEqual(left, {past.pk, with_reason.pk})


class BlockBarberRangeTests(TestCase):
    def setUp(self):
        shop = Barbershop.objects.create(name='Área 30 Test')
        user = User.objects.create_user('frank_b', password='x')
        self.frank = Barber.objects.create(user=user, barbershop=shop, display_name='Franko')
        self.d0 = timezone.localdate()
        self.d1 = self.d0 + timedelta(days=9)
        BarberUnavailability.objects.create(
            barber=self.frank, date=self.d0 + timedelta(days=1),
            start_time=time(13, 0), end_time=time(21, 0))
        svc = Service.objects.create(name='Corte', slug='corte-b', price=Decimal('30000'))
        Booking.objects.create(client_name='Previa', barber=self.frank, service=svc,
                               date=self.d0 + timedelta(days=1), time=time(11, 0),
                               price=Decimal('30000'), status='pending')

    def _run(self, **extra):
        out = StringIO()
        call_command('block_barber_range', barber='frank', date_from=self.d0.isoformat(),
                     date_to=self.d1.isoformat(), reason='Sin reservas', stdout=out, **extra)
        return out.getvalue()

    def test_simulacion_no_cambia_nada(self):
        out = self._run(replace=True)
        self.assertIn('Simulación', out)
        self.assertEqual(BarberUnavailability.objects.filter(barber=self.frank).count(), 1)

    def test_bloquea_el_dia_completo_y_lista_las_citas(self):
        out = self._run(replace=True, apply=True)
        blocks = BarberUnavailability.objects.filter(barber=self.frank)
        self.assertEqual(blocks.count(), 10)
        self.assertTrue(all(u.start_time == time(0, 0) and u.end_time >= time(23, 59) for u in blocks))
        self.assertIn('Previa', out)
        # Ya no hay ninguna franja libre para reservar en el rango.
        self.assertIsNotNone(Booking.objects.get(client_name='Previa'))
