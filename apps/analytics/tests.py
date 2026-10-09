"""Tests de "Mis Estadísticas" (apps/analytics/barber_stats.py).

Caso real que los originó: el 7-oct Jesús atendió 3 servicios ($100.000) pero
el tercero se cobró al día siguiente y su tablero mostraba $60.000, además de
mostrar lo vendido como si fuera lo que él gana.
"""
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.analytics.barber_stats import compute_barber_stats
from apps.barbers.models import Barber
from apps.bookings.models import Booking
from apps.cashflow.models import Commission, Sale
from apps.services.models import Service
from apps.users.models import Barbershop, UserProfile

DAY = date(2026, 10, 7)


class BarberStatsTests(TestCase):
    def setUp(self):
        shop = Barbershop.objects.create(name='Área 30 Test')
        self.user = User.objects.create_user('jesus_t', password='x')
        UserProfile.objects.create(user=self.user, role='barber', barbershop=shop)
        self.barber = Barber.objects.create(
            user=self.user, barbershop=shop, display_name='Jesús',
            commission_percentage=Decimal('45'),
        )
        other_user = User.objects.create_user('otro_t', password='x')
        UserProfile.objects.create(user=other_user, role='barber', barbershop=shop)
        self.other = Barber.objects.create(user=other_user, barbershop=shop, display_name='Otro')
        self.svc = Service.objects.create(name='Silver', slug='silver-t', price=Decimal('30000'))

    def _sale(self, t, price, paid_on=None, status='approved', tip=0, barber=None):
        barber = barber or self.barber
        bk = Booking.objects.create(
            client_name=f'Cliente {t}', client_phone=f'300{t.hour:02d}{t.minute:02d}000',
            barber=barber, service=self.svc, date=DAY, time=t,
            price=Decimal(price), status='completed',
        )
        sale = Sale.objects.create(
            booking=bk, barber=barber, service=self.svc, base_price=Decimal(price),
            tip_amount=Decimal(tip), approval_status=status,
        )
        # Se cobra el mismo día del servicio, salvo que se diga otra cosa.
        stamp = timezone.make_aware(timezone.datetime.combine(paid_on or DAY, time(20, 0)))
        Sale.objects.filter(pk=sale.pk).update(created_at=stamp)
        Commission.objects.create(sale=sale, barber=barber, percentage=Decimal('45'))
        return sale

    def test_cuenta_el_dia_del_servicio_y_separa_vendido_de_ganado(self):
        self._sale(time(15, 0), 30000)
        self._sale(time(17, 26), 30000)
        self._sale(time(18, 28), 40000, paid_on=DAY + timedelta(days=1))
        t = compute_barber_stats(self.barber, DAY, DAY)['totals']
        self.assertEqual(t['sold'], 100000)
        self.assertEqual(t['earned'], 45000)
        self.assertEqual(t['services'], 3)
        self.assertEqual(t['paid_later'], 1)
        # El día siguiente no se lleva la venta cobrada tarde.
        nxt = compute_barber_stats(self.barber, DAY + timedelta(days=1), DAY + timedelta(days=1))
        self.assertEqual(nxt['totals']['sold'], 0)

    def test_rechazadas_fuera_pendientes_marcadas_propinas_suman(self):
        self._sale(time(10, 0), 30000, tip=5000)
        self._sale(time(11, 0), 30000, status='pending')
        self._sale(time(12, 0), 30000, status='rejected')
        t = compute_barber_stats(self.barber, DAY, DAY)['totals']
        self.assertEqual(t['sold'], 60000)
        self.assertEqual(t['tips'], 5000)
        self.assertEqual(t['earned'], 13500 + 5000 + 13500)
        self.assertEqual((t['pending_count'], t['pending_sold']), (1, 30000))

    def test_solo_cuenta_las_ventas_del_barbero(self):
        self._sale(time(10, 0), 30000)
        self._sale(time(11, 0), 30000, barber=self.other)
        self.assertEqual(compute_barber_stats(self.barber, DAY, DAY)['totals']['services'], 1)

    def test_api_y_permisos(self):
        self._sale(time(10, 0), 30000)
        self.client.force_login(self.user)
        r = self.client.get(f'/api/admin/stats/barber/?start={DAY}&end={DAY}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['totals']['sold'], 30000)
        self.assertEqual(len(r.json()['series']), 1)
        # Un barbero no puede ver las ventas de otro.
        r = self.client.get(f'/api/admin/stats/barber/?barber={self.other.id}')
        self.assertEqual(r.status_code, 403)

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_dashboard_del_barbero_usa_el_dia_del_servicio(self):
        self._sale(time(18, 28), 40000, paid_on=DAY + timedelta(days=1))
        self.client.force_login(self.user)
        r = self.client.get(f'/admin-panel/?date={DAY}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['barber_day']['sold'], '40.000')
        self.assertEqual(r.context['barber_day']['earned'], '18.000')
        self.assertEqual(self.client.get('/admin-panel/mis-estadisticas/').status_code, 200)
