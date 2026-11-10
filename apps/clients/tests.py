"""Tarjeta de sellos (apps/clients/loyalty.py).

Regla del dueño (nov-2026): un sello cuenta solo cuando el servicio se cobró y
la venta quedó APROBADA en caja — reservar no suma. Suman los servicios desde
$30.000 y cada sello vence a los 6 meses.
"""
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.barbers.models import Barber
from apps.bookings.models import Booking
from apps.cashflow.models import Sale
from apps.services.models import Service
from apps.users.models import Barbershop, UserProfile

from .loyalty import add_months, build_card, phone_key
from .models import LoyaltyRedemption, LoyaltySettings

TODAY = timezone.localdate()
PHONE = '311 265 1032'


class TarjetaDeSellosTests(TestCase):
    def setUp(self):
        self.shop = Barbershop.objects.create(name='Área 30 Test')
        user = User.objects.create_user('barbero_t', password='x')
        UserProfile.objects.create(user=user, role='barber', barbershop=self.shop)
        self.barber = Barber.objects.create(user=user, barbershop=self.shop, display_name='Frank')
        self.silver = Service.objects.create(name='Silver Premium', slug='silver-t', price=Decimal('30000'))
        self.barba = Service.objects.create(name='Diseño de barba', slug='barba-t', price=Decimal('15000'))
        self._minute = 0

    def _booking(self, day, service=None, phone=PHONE, status='completed'):
        self._minute += 1
        service = service or self.silver
        return Booking.objects.create(
            client_name='Carlos Ruiz', client_phone=phone, barber=self.barber, service=service,
            date=day, time=time(8 + self._minute // 60, self._minute % 60),
            price=service.price, status=status,
        )

    def _paid(self, day=None, service=None, phone=PHONE, approval='approved', discount=0):
        service = service or self.silver
        bk = self._booking(day or TODAY - timedelta(days=1), service, phone)
        return Sale.objects.create(
            booking=bk, barber=self.barber, service=service, base_price=service.price,
            discount_amount=Decimal(discount), approval_status=approval,
        )

    def _user(self, username, role):
        user = User.objects.create_user(username, password='x')
        UserProfile.objects.create(user=user, role=role, barbershop=self.shop)
        return user

    # ── Qué suma y qué no ──────────────────────────────────
    def test_solo_suma_la_venta_aprobada_en_caja(self):
        self._booking(TODAY + timedelta(days=2), status='confirmed')   # solo reservó
        self._paid(approval='pending')                                 # cobrada, sin aprobar
        self._paid(approval='rejected')
        self.assertIsNone(build_card(PHONE))
        self._paid()
        self.assertEqual(build_card(PHONE)['active'], 1)

    def test_suman_servicios_desde_30000_y_el_gratis_no(self):
        self._paid(service=self.barba)                     # $15.000: no suma
        self._paid(discount=30000)                         # premio en $0: no suma
        self._paid(discount=5000)                          # con descuento sí suma
        card = build_card(PHONE)
        self.assertEqual(card['active'], 1)
        self.assertEqual(card['stamps'][0]['price'], 30000)

    def test_el_mismo_celular_escrito_distinto_es_la_misma_tarjeta(self):
        self._paid(phone='311 265 1032')
        self._paid(phone='+57 311-265-1032')
        self._paid(phone='3112651032')
        self.assertEqual(phone_key('+57 311 265 1032'), '3112651032')
        self.assertEqual(build_card('3112651032')['active'], 3)

    def test_cada_sello_vence_a_los_6_meses(self):
        self._paid(day=add_months(TODAY, -6))                       # vence hoy
        self._paid(day=add_months(TODAY, -6) + timedelta(days=1))   # vence mañana
        card = build_card(PHONE)
        self.assertEqual(card['active'], 1)
        self.assertEqual([s['state'] for s in card['stamps']], ['activo', 'vencido'])
        self.assertEqual(card['next_expiry'], (TODAY + timedelta(days=1)).isoformat())

    def test_add_months_respeta_fin_de_mes(self):
        self.assertEqual(add_months(date(2026, 8, 31), 6), date(2027, 2, 28))
        self.assertEqual(add_months(date(2026, 11, 9), 6), date(2027, 5, 9))

    def test_cambiar_reglas_recalcula(self):
        self._paid(service=self.barba)
        self.assertIsNone(build_card(PHONE))
        cfg = LoyaltySettings.load()
        cfg.min_service_price = 15000
        cfg.save()
        self.assertEqual(build_card(PHONE)['active'], 1)

    # ── Canje ──────────────────────────────────────────────
    def test_canje_gasta_los_10_mas_antiguos(self):
        for i in range(11):
            self._paid(day=TODAY - timedelta(days=30 - i))
        self.assertTrue(build_card(PHONE)['complete'])
        LoyaltyRedemption.objects.create(phone=phone_key(PHONE), stamps_used=10)
        card = build_card(PHONE)
        self.assertEqual(card['active'], 1)
        self.assertFalse(card['complete'])
        # El que queda vigente es el más reciente.
        self.assertEqual(card['stamps'][0]['state'], 'activo')
        self.assertEqual(sum(s['state'] == 'usado' for s in card['stamps']), 10)

    def test_api_canjear_permisos_y_validacion(self):
        for i in range(9):
            self._paid(day=TODAY - timedelta(days=20 - i))
        url = '/api/admin/loyalty/3112651032/redeem/'

        self.client.force_login(self._user('frank_t', 'operational_admin'))
        r = self.client.post(url, {}, content_type='application/json')
        self.assertEqual(r.status_code, 400)               # 9 de 10: no se puede
        self.assertIn('9 de 10', r.json()['error'])

        self._paid()
        r = self.client.post(url, {'notes': 'cita del sábado'}, content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['card']['active'], 0)
        self.assertEqual(self.client.post(url, {}, content_type='application/json').status_code, 400)

        # Un admin "normal" ve las tarjetas pero no canjea; un barbero no entra.
        self.client.force_login(self._user('admin_t', 'admin'))
        self.assertEqual(self.client.get('/api/admin/loyalty/').status_code, 200)
        self.assertEqual(self.client.post(url, {}, content_type='application/json').status_code, 403)
        self.client.force_login(self.barber.user)
        self.assertEqual(self.client.get('/api/admin/loyalty/').status_code, 403)

    def test_deshacer_canje_devuelve_los_sellos(self):
        for i in range(10):
            self._paid(day=TODAY - timedelta(days=20 - i))
        red = LoyaltyRedemption.objects.create(phone='3112651032', stamps_used=10)
        self.client.force_login(self._user('frank_t', 'operational_admin'))
        url = f'/api/admin/loyalty/redemptions/{red.pk}/'
        self.assertEqual(self.client.delete(url).status_code, 403)   # solo socios
        self.client.force_login(self._user('camilo_t', 'superadmin'))
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(build_card(PHONE)['active'], 10)

    # ── Reglas ─────────────────────────────────────────────
    def test_solo_los_socios_cambian_las_reglas(self):
        url = '/api/admin/loyalty/settings/'
        body = {'stamps_required': 8, 'min_service_price': 40000, 'expiry_months': 12,
                'reward_service_id': self.silver.pk, 'reward_note': 'o paga la diferencia'}
        self.client.force_login(self._user('frank_t', 'operational_admin'))
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.put(url, body, content_type='application/json').status_code, 403)

        self.client.force_login(self._user('camilo_t', 'superadmin'))
        r = self.client.put(url, body, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        cfg = LoyaltySettings.load()
        self.assertEqual((cfg.stamps_required, int(cfg.min_service_price), cfg.expiry_months), (8, 40000, 12))
        self.assertEqual(cfg.reward_service, self.silver)

        r = self.client.put(url, {**body, 'stamps_required': 0}, content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('stamps_required', r.json()['errors'])

    def test_lista_y_busqueda(self):
        self._paid()
        self._paid(phone='300 000 0000')
        self.client.force_login(self._user('admin_t', 'admin'))
        data = self.client.get('/api/admin/loyalty/').json()
        self.assertEqual(data['summary']['clients'], 2)
        self.assertEqual(data['settings']['min_service_price'], 30000)
        found = self.client.get('/api/admin/loyalty/?search=265 1032').json()['cards']
        self.assertEqual([c['phone'] for c in found], ['3112651032'])

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_pagina_del_panel(self):
        self.client.force_login(self._user('admin_t', 'admin'))
        r = self.client.get('/admin-panel/sellos/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Tarjeta de sellos')
        self.assertContains(r, 'En desarrollo')
        self.assertContains(r, 'const CAN_REDEEM = false')
        self.client.force_login(self.barber.user)
        self.assertEqual(self.client.get('/admin-panel/sellos/').status_code, 302)
