"""Tests de merge_user_accounts: unir dos cuentas sin perder historial."""
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from apps.analytics.models import AuditLog
from apps.barbers.models import Barber, BarberUnavailability
from apps.users.models import Barbershop, UserProfile


class MergeUserAccountsTests(TestCase):
    def setUp(self):
        shop = Barbershop.objects.create(name='Área 30 Test')
        self.admin = User.objects.create_user('cristian.admin', password='x')
        UserProfile.objects.create(user=self.admin, role='superadmin', barbershop=shop)
        self.old = User.objects.create_user('cristiang', password='x', email='c@x.co')
        UserProfile.objects.create(user=self.old, role='barber', barbershop=shop)
        self.barber = Barber.objects.create(
            user=self.old, barbershop=shop, display_name='Cristian',
            commission_percentage=Decimal('50'),
        )
        BarberUnavailability.objects.create(
            barber=self.barber, date='2026-12-01', start_time='10:00', end_time='11:00',
        )
        AuditLog.objects.create(user=self.old, action='login')

    def test_simulacion_no_cambia_nada(self):
        call_command('merge_user_accounts', keep='cristian.admin', remove='cristiang', stdout=StringIO())
        self.assertTrue(User.objects.filter(username='cristiang').exists())
        self.barber.refresh_from_db()
        self.assertEqual(self.barber.user, self.old)

    def test_une_y_borra_sin_perder_el_barbero(self):
        call_command('merge_user_accounts', keep='cristian.admin', remove='cristiang',
                     email='c@x.co', role='superadmin', apply=True, stdout=StringIO())
        self.assertFalse(User.objects.filter(username='cristiang').exists())
        self.barber.refresh_from_db()
        self.assertEqual(self.barber.user, self.admin)
        self.assertEqual(BarberUnavailability.objects.filter(barber=self.barber).count(), 1)
        self.assertEqual(AuditLog.objects.filter(user=self.admin, action='login').count(), 1)
        self.assertTrue(AuditLog.objects.filter(object_repr__startswith='Unión de cuentas').exists())
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser)
        self.assertEqual(self.admin.profile.role, 'superadmin')
        self.assertEqual(self.admin.email, 'c@x.co')
