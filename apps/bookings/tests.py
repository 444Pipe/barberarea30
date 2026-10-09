"""Tests de reservas vs. bloqueos de inactividad, walk-in, teléfono y agenda.

Nacen del caso de oct-2026: Frank bloqueado hasta el 31-dic y seguían
apareciendo citas con él. Cubren cada camino por el que una cita podía caer
encima de un bloqueo y lo que ve el barbero en su agenda.
"""
from datetime import time, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.barbers.models import Barber, BarberUnavailability
from apps.bookings.holidays import is_holiday
from apps.bookings.models import Booking
from apps.bookings.validators import bookings_in_unavailability
from apps.services.models import Service
from apps.users.models import Barbershop, UserProfile


def _next_working_wednesday():
    d = timezone.localdate() + timedelta(days=7)
    while d.weekday() != 2 or is_holiday(d):
        d += timedelta(days=1)
    return d


# Los correos se mandan en un hilo aparte; en tests no hace falta.
@mock.patch('threading.Thread')
class BookingBlockTests(TestCase):
    def setUp(self):
        self.shop = Barbershop.objects.create(name='Área 30 Test')
        frank_user = User.objects.create_user('frank_t', password='x')
        UserProfile.objects.create(user=frank_user, role='operational_admin', barbershop=self.shop)
        self.frank_user = frank_user
        self.frank = Barber.objects.create(
            user=frank_user, barbershop=self.shop, display_name='Frank', display_order=0,
        )
        carlos_user = User.objects.create_user('carlos_t', password='x')
        UserProfile.objects.create(user=carlos_user, role='barber', barbershop=self.shop)
        self.carlos_user = carlos_user
        self.carlos = Barber.objects.create(
            user=carlos_user, barbershop=self.shop, display_name='Carlos', display_order=1,
        )
        self.service = Service.objects.create(
            name='Corte', slug='corte-t', price=Decimal('30000'), duration_minutes=60,
        )
        self.day = _next_working_wednesday()

    def _block(self, barber, start=time(0, 0), end=time(23, 59, 59), day=None):
        return BarberUnavailability.objects.create(
            barber=barber, date=day or self.day, start_time=start, end_time=end,
        )

    def _public(self, **extra):
        payload = {
            'client_name': 'Cliente', 'client_phone': '3001234567',
            'service_id': self.service.id, 'barber_id': self.frank.id,
            'date': self.day.strftime('%Y-%m-%d'), 'time': '11:00',
            'privacy_accepted': True,
        }
        payload.update(extra)
        return self.client.post('/api/bookings/', payload, content_type='application/json')

    # ── Sitio público ──────────────────────────────────────────────
    def test_publico_no_reserva_sobre_bloqueo(self, _thread):
        self._block(self.frank)
        r = self._public()
        self.assertEqual(r.status_code, 409)
        self.assertFalse(Booking.objects.exists())

    def test_publico_no_puede_mandar_walkin_ni_force(self, _thread):
        self._block(self.frank)
        r = self._public(is_walk_in=True, force=True)
        self.assertEqual(r.status_code, 409)
        self.assertFalse(Booking.objects.exists())

    def test_hora_con_segundos_igual_revisa_bloqueo(self, _thread):
        self._block(self.frank)
        r = self._public(time='11:00:00')
        self.assertEqual(r.status_code, 409)
        self.assertFalse(Booking.objects.exists())

    def test_formato_raro_es_400_y_no_se_salta_chequeos(self, _thread):
        # Antes un formato que DRF sí aceptaba pero strptime no, saltaba TODO.
        self._block(self.frank)
        r = self._public(time='1100')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Booking.objects.exists())

    def test_bloqueo_parcial_cuenta_las_2h_de_frank(self, _thread):
        # Frank ocupa 2h: a las 11:00 se cruza con un bloqueo de 12:30 a 13:00.
        self._block(self.frank, time(12, 30), time(13, 0))
        self.assertEqual(self._public().status_code, 409)

    def test_cualquier_barbero_no_asigna_al_bloqueado(self, _thread):
        self._block(self.frank)
        r = self._public(barber_id='any')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Booking.objects.get().barber, self.carlos)

    def test_publico_sin_bloqueo_si_reserva(self, _thread):
        r = self._public()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Booking.objects.get().duration_minutes, 120)

    # ── Walk-in del panel ──────────────────────────────────────────
    def test_walkin_exige_sesion(self, _thread):
        r = self.client.post('/api/admin/bookings/walk-in/', {
            'service_id': self.service.id, 'barber_id': self.frank.id,
            'date': self.day.strftime('%Y-%m-%d'), 'time': '11:00',
        }, content_type='application/json')
        self.assertIn(r.status_code, (401, 403))
        self.assertFalse(Booking.objects.exists())

    def test_walkin_del_personal_puede_forzar_con_confirmacion(self, _thread):
        self._block(self.frank)
        self.client.force_login(self.carlos_user)
        body = {
            'client_name': 'Walk', 'service_id': self.service.id,
            'barber_id': self.frank.id, 'date': self.day.strftime('%Y-%m-%d'), 'time': '11:00',
        }
        r = self.client.post('/api/admin/bookings/walk-in/', body, content_type='application/json')
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json()['requires_override'])
        r = self.client.post('/api/admin/bookings/walk-in/', {**body, 'force': True},
                             content_type='application/json')
        self.assertEqual(r.status_code, 201)
        bk = Booking.objects.get()
        self.assertTrue(bk.is_walk_in)
        self.assertIn('bloqueo de inactividad', bk.notes)

    # ── Reactivar una cita cancelada ───────────────────────────────
    def test_reactivar_cancelada_sobre_bloqueo_se_rechaza(self, _thread):
        bk = Booking.objects.create(
            client_name='X', barber=self.frank, service=self.service,
            date=self.day, time=time(11, 0), duration_minutes=120,
            price=Decimal('30000'), status='cancelled',
        )
        self._block(self.frank)
        self.client.force_login(self.frank_user)
        r = self.client.patch(f'/api/admin/bookings/{bk.id}/', {'status': 'confirmed'},
                              content_type='application/json')
        self.assertEqual(r.status_code, 409)
        bk.refresh_from_db()
        self.assertEqual(bk.status, 'cancelled')

    # ── Citas que ya existían antes del bloqueo ────────────────────
    def test_lista_citas_activas_dentro_de_bloqueos(self, _thread):
        bk = Booking.objects.create(
            client_name='Previa', client_phone='3001112233', barber=self.frank,
            service=self.service, date=self.day, time=time(15, 0),
            duration_minutes=120, price=Decimal('30000'), status='confirmed',
        )
        self._block(self.frank)
        hits = bookings_in_unavailability(barber=self.frank)
        self.assertEqual([h['booking'].id for h in hits], [bk.id])

        self.client.force_login(self.frank_user)
        r = self.client.get(f'/api/admin/barbers/{self.frank.id}/unavailability/conflicts/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()[0]['id'], bk.id)
        self.assertTrue(r.json()[0]['created_before_block'])

    # ── Teléfono y agenda del barbero ──────────────────────────────
    def test_barbero_ve_el_telefono_de_sus_clientes(self, _thread):
        Booking.objects.create(
            client_name='Ana', client_phone='3009998877', barber=self.carlos,
            service=self.service, date=self.day, time=time(11, 0),
            duration_minutes=60, price=Decimal('30000'), status='confirmed',
        )
        self.client.force_login(self.carlos_user)
        r = self.client.get('/api/admin/bookings/')
        self.assertEqual(r.json()[0]['client_phone'], '3009998877')

    def test_agenda_del_barbero(self, _thread):
        Booking.objects.create(
            client_name='Ana', client_phone='3009998877', barber=self.carlos,
            service=self.service, date=self.day, time=time(11, 0),
            duration_minutes=60, price=Decimal('30000'), status='confirmed',
        )
        self._block(self.carlos, time(11, 30), time(12, 0))
        self.client.force_login(self.carlos_user)
        ds = self.day.strftime('%Y-%m-%d')
        r = self.client.get(f'/api/admin/my-agenda/?start={ds}&end={ds}')
        self.assertEqual(r.status_code, 200)
        day = r.json()['days'][0]
        bk = day['bookings'][0]
        self.assertEqual(bk['client_phone'], '3009998877')
        self.assertEqual(bk['end_time'], '12:00')
        self.assertTrue(bk['in_block'])
        self.assertEqual(day['window']['start'], '10:00')
        self.assertEqual(len(day['blocks']), 1)
        self.assertEqual(day['totals']['active'], 1)
        # El barbero ve lo que ganaría (comisión por defecto 40%), no el precio.
        self.assertNotIn('price', bk)
        self.assertNotIn('value', day['totals'])
        self.assertEqual(bk['earn_estimate'], 12000)

        # Un barbero no puede ver la agenda de otro.
        r = self.client.get(f'/api/admin/my-agenda/?barber={self.frank.id}')
        self.assertEqual(r.status_code, 403)


@mock.patch('threading.Thread')
class WorkHoursTests(TestCase):
    """Horario de trabajo temporal: "del X al Y trabaja de H1 a H2"."""

    def setUp(self):
        self.shop = Barbershop.objects.create(name='Área 30 Test')
        self.frank_user = User.objects.create_user('frank_w', password='x')
        UserProfile.objects.create(user=self.frank_user, role='operational_admin', barbershop=self.shop)
        self.frank = Barber.objects.create(user=self.frank_user, barbershop=self.shop, display_name='Frank')
        self.service = Service.objects.create(
            name='Corte', slug='corte-w', price=Decimal('30000'), duration_minutes=60,
        )
        self.day = _next_working_wednesday()
        self.client.force_login(self.frank_user)
        r = self.client.post(f'/api/admin/barbers/{self.frank.id}/work-hours/', {
            'date_from': self.day.strftime('%Y-%m-%d'),
            'date_to': (self.day + timedelta(days=30)).strftime('%Y-%m-%d'),
            'start_time': '10:00', 'end_time': '13:00', 'reason': 'Solo mañanas',
        }, content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.client.logout()

    def _public(self, t):
        return self.client.post('/api/bookings/', {
            'client_name': 'Cliente', 'client_phone': '3001234567',
            'service_id': self.service.id, 'barber_id': self.frank.id,
            'date': self.day.strftime('%Y-%m-%d'), 'time': t, 'privacy_accepted': True,
        }, content_type='application/json')

    def test_ventana_recortada(self, _thread):
        w = self.frank.day_window(self.day)
        self.assertEqual((w['start'], w['end'], w['source']), (time(10, 0), time(13, 0), 'custom'))
        # Fuera del rango de fechas sigue el horario normal.
        self.assertEqual(self.frank.day_window(self.day - timedelta(days=7))['end'], time(20, 0))

    def test_web_solo_ofrece_la_franja(self, _thread):
        r = self.client.get(f'/api/barbers/{self.frank.id}/availability/'
                            f'?date={self.day:%Y-%m-%d}&service_id={self.service.id}')
        libres = [s['time'] for s in r.json()['slots'] if s['available']]
        # Frank ocupa 2 h: la última que cabe antes de la 1 p.m. es a las 11:00.
        self.assertEqual(libres, ['10:00', '10:30', '11:00'])

    def test_reserva_fuera_del_horario_se_rechaza(self, _thread):
        self.assertEqual(self._public('11:30').status_code, 409)
        self.assertEqual(self._public('15:00').status_code, 409)
        self.assertEqual(self._public('11:00').status_code, 201)

    def test_cita_previa_fuera_del_horario_aparece_en_conflictos(self, _thread):
        Booking.objects.create(
            client_name='Previa', barber=self.frank, service=self.service,
            date=self.day, time=time(15, 0), duration_minutes=120,
            price=Decimal('30000'), status='confirmed',
        )
        self.client.force_login(self.frank_user)
        r = self.client.get(f'/api/admin/barbers/{self.frank.id}/unavailability/conflicts/')
        self.assertEqual([c['kind'] for c in r.json()], ['hours'])

    def test_agenda_muestra_horario_especial(self, _thread):
        self.client.force_login(self.frank_user)
        ds = self.day.strftime('%Y-%m-%d')
        day = self.client.get(f'/api/admin/my-agenda/?start={ds}&end={ds}').json()['days'][0]
        self.assertEqual(day['window']['source'], 'custom')
        self.assertEqual(day['window']['end'], '13:00')
        self.assertEqual(day['window']['reason'], 'Solo mañanas')
