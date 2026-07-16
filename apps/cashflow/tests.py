"""Tests de la liquidación a barberos: registro, detalle y anulación.

Cubren el flujo que permite a un superadmin corregir un pago metido de más:
al liquidar queda un `BarberPayment` con las comisiones y vales que cubrió
apuntando a él, y borrarlo revierte exactamente eso y nada más.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.barbers.models import Barber
from apps.cashflow.models import (
    BarberAdvance, BarberPayment, Commission, DailyClose, Expense, Sale,
)
from apps.cashflow.services import MATERIALS_EXPENSE_PREFIX, is_materials_expense
from apps.users.models import Barbershop, UserProfile


class BarberPaymentTests(TestCase):
    def setUp(self):
        self.shop = Barbershop.objects.create(name='Área 30 Test')

        self.frank_user = User.objects.create_user('frank_test', password='x')
        UserProfile.objects.create(user=self.frank_user, role='operational_admin',
                                   barbershop=self.shop)
        self.camilo = User.objects.create_user('camilo_test', password='x')
        UserProfile.objects.create(user=self.camilo, role='superadmin',
                                   barbershop=self.shop)

        barber_user = User.objects.create_user('barbero_test', password='x')
        self.barber = Barber.objects.create(
            user=barber_user, barbershop=self.shop, display_name='Carlos Test',
            commission_percentage=Decimal('50.00'),
        )

    def _venta(self, base_price=50000, tip=0):
        """Una venta aprobada con su comisión, como la dejaría el checkout."""
        sale = Sale.objects.create(
            barber=self.barber, base_price=Decimal(base_price),
            tip_amount=Decimal(tip), approval_status=Sale.STATUS_APPROVED,
        )
        return Commission.objects.create(
            sale=sale, barber=self.barber, percentage=Decimal('50.00'),
        )

    def _pagar(self):
        self.client.force_login(self.frank_user)
        return self.client.post(
            reverse('cashflow_pay_barber_api', args=[self.barber.id])
        )

    # ── Registro ──────────────────────────────────────────────────────────

    def test_liquidar_deja_constancia_del_pago(self):
        c1 = self._venta(50000, tip=5000)
        c2 = self._venta(30000)
        vale = BarberAdvance.objects.create(barber=self.barber, amount=Decimal('10000'))

        resp = self._pagar()
        self.assertEqual(resp.status_code, 200, resp.content)

        payment = BarberPayment.objects.get(barber=self.barber)
        # 25000 + 5000 (propina) + 15000 − 10000 (vale) = 35000
        self.assertEqual(payment.amount, Decimal('35000'))
        self.assertIsNone(payment.daily_close, 'Un pago manual no nace de un cierre')
        self.assertEqual(payment.created_by, self.frank_user)

        # Las comisiones y el vale quedan enlazados al pago que los cubrió.
        for c in (c1, c2):
            c.refresh_from_db()
            self.assertTrue(c.is_paid)
            self.assertEqual(c.paid_in_payment, payment)
        vale.refresh_from_db()
        self.assertTrue(vale.is_settled)
        self.assertEqual(vale.settled_in_payment, payment)

    # ── Detalle ───────────────────────────────────────────────────────────

    def test_detalle_desglosa_los_servicios(self):
        self._venta(50000, tip=5000)
        self._venta(30000)
        BarberAdvance.objects.create(barber=self.barber, amount=Decimal('10000'))

        self.client.force_login(self.frank_user)
        resp = self.client.get(
            reverse('cashflow_barber_payment_detail_api', args=[self.barber.id])
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()

        self.assertEqual(len(d['services']), 2)
        self.assertEqual(d['totals']['commissions'], 40000)   # 25000 + 15000
        self.assertEqual(d['totals']['tips'], 5000)
        self.assertEqual(d['totals']['advances'], 10000)
        self.assertEqual(d['totals']['net_payable'], 35000)
        self.assertFalse(d['is_frank'])
        # Frank es operational_admin: no puede borrar pagos.
        self.assertFalse(d['is_superadmin'])

    def test_detalle_marca_borrable_solo_para_superadmin(self):
        self._venta(50000)
        self._pagar()

        self.client.force_login(self.frank_user)
        d = self.client.get(
            reverse('cashflow_barber_payment_detail_api', args=[self.barber.id])
        ).json()
        self.assertFalse(d['payments'][0]['can_delete'])

        self.client.force_login(self.camilo)
        d = self.client.get(
            reverse('cashflow_barber_payment_detail_api', args=[self.barber.id])
        ).json()
        self.assertTrue(d['payments'][0]['can_delete'])

    # ── Anulación ─────────────────────────────────────────────────────────

    def test_frank_no_puede_borrar_un_pago(self):
        self._venta(50000)
        self._pagar()
        payment = BarberPayment.objects.get(barber=self.barber)

        self.client.force_login(self.frank_user)
        resp = self.client.delete(
            reverse('cashflow_delete_barber_payment_api', args=[payment.id])
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(BarberPayment.objects.filter(pk=payment.id).exists())

    def test_superadmin_borra_el_pago_y_revierte_lo_que_cubrio(self):
        comm = self._venta(50000)
        vale = BarberAdvance.objects.create(barber=self.barber, amount=Decimal('10000'))
        self._pagar()
        payment = BarberPayment.objects.get(barber=self.barber)

        self.client.force_login(self.camilo)
        resp = self.client.delete(
            reverse('cashflow_delete_barber_payment_api', args=[payment.id])
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(BarberPayment.objects.filter(pk=payment.id).exists())

        comm.refresh_from_db()
        self.assertFalse(comm.is_paid, 'La comisión vuelve a quedar pendiente')
        self.assertIsNone(comm.paid_at)
        self.assertIsNone(comm.paid_in_payment)

        vale.refresh_from_db()
        self.assertFalse(vale.is_settled)
        self.assertIsNone(vale.settled_in_payment)

    def test_borrar_un_pago_no_toca_liquidaciones_anteriores(self):
        vieja = self._venta(50000)
        self._pagar()
        pago_viejo = BarberPayment.objects.get(barber=self.barber)

        nueva = self._venta(30000)
        self._pagar()
        pago_nuevo = BarberPayment.objects.exclude(pk=pago_viejo.pk).get()

        self.client.force_login(self.camilo)
        resp = self.client.delete(
            reverse('cashflow_delete_barber_payment_api', args=[pago_nuevo.id])
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        nueva.refresh_from_db()
        self.assertFalse(nueva.is_paid, 'La comisión del pago borrado vuelve a pendiente')
        vieja.refresh_from_db()
        self.assertTrue(vieja.is_paid, 'La liquidación anterior queda intacta')
        self.assertEqual(vieja.paid_in_payment, pago_viejo)

    # El storage por defecto exige un manifiesto de collectstatic, que en tests
    # no existe. Lo cambiamos para poder validar el template en sí.
    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_la_pantalla_de_caja_renderiza_el_boton_de_detalle(self):
        self.client.force_login(self.frank_user)
        resp = self.client.get(reverse('admin_cashflow'))
        self.assertEqual(resp.status_code, 200, resp.content[:3000])
        html = resp.content.decode()
        self.assertIn('openPaymentDetail', html)
        self.assertIn('cf-modal-pay-detail', html)

    def test_el_pago_de_un_cierre_no_se_borra_por_aqui(self):
        cierre = DailyClose.objects.create(date=date.today() - timedelta(days=1),
                                           closed_by=self.frank_user)
        payment = BarberPayment.objects.create(
            barber=self.barber, daily_close=cierre, amount=Decimal('20000'),
            created_by=self.frank_user,
        )

        self.client.force_login(self.camilo)
        resp = self.client.delete(
            reverse('cashflow_delete_barber_payment_api', args=[payment.id])
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('cierre', resp.json()['error'].lower())
        self.assertTrue(BarberPayment.objects.filter(pk=payment.id).exists())


class MaterialesEnElCierreTests(TestCase):
    """El costo de materiales se separa del resto de egresos en el detalle,
    sin dejar de sumar en total_expenses (la fórmula del neto no cambia).
    """

    def setUp(self):
        self.shop = Barbershop.objects.create(name='Área 30 Test')
        self.frank_user = User.objects.create_user('frank_mat', password='x')
        UserProfile.objects.create(user=self.frank_user, role='operational_admin',
                                   barbershop=self.shop)
        self.client.force_login(self.frank_user)

    def test_reconoce_el_egreso_de_materiales_por_su_prefijo(self):
        self.assertTrue(is_materials_expense(f'{MATERIALS_EXPENSE_PREFIX} Juan (venta #3)'))
        self.assertFalse(is_materials_expense('Arriendo local'))
        self.assertFalse(is_materials_expense(''))
        self.assertFalse(is_materials_expense(None))

    def test_el_detalle_del_cierre_separa_materiales_de_los_demas_egresos(self):
        cierre = DailyClose.objects.create(
            date=date.today(), closed_by=self.frank_user,
            total_expenses=Decimal('80000'),
        )
        Expense.objects.create(
            description=f'{MATERIALS_EXPENSE_PREFIX} Juan (venta #1)',
            amount=Decimal('20000'), expense_type='variable',
            included_in_daily_close=cierre,
        )
        Expense.objects.create(
            description=f'{MATERIALS_EXPENSE_PREFIX} Pedro (venta #2)',
            amount=Decimal('10000'), expense_type='variable',
            included_in_daily_close=cierre,
        )
        Expense.objects.create(
            description='Arriendo local', amount=Decimal('50000'),
            expense_type='fixed', included_in_daily_close=cierre,
        )

        resp = self.client.get(
            reverse('admin_daily_close_detail_api', args=[cierre.id])
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()

        self.assertEqual(d['total_materials'], 30000)
        # Sigue siendo un subconjunto de los egresos, no un rubro aparte.
        self.assertEqual(d['total_expenses'], 80000)

        materiales = [e for e in d['expenses'] if e['is_materials']]
        otros = [e for e in d['expenses'] if not e['is_materials']]
        self.assertEqual(len(materiales), 2)
        self.assertEqual([e['description'] for e in otros], ['Arriendo local'])
