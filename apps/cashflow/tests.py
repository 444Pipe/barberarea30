"""Tests de la liquidación a barberos: registro, detalle y anulación.

Cubren el flujo que permite a un superadmin corregir un pago metido de más:
al liquidar queda un `BarberPayment` con las comisiones y vales que cubrió
apuntando a él, y borrarlo revierte exactamente eso y nada más.
"""
import io
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from apps.barbers.models import Barber
from apps.cashflow.models import (
    BarberAdvance, BarberPayment, Commission, DailyClose, Expense, Sale,
)
from apps.cashflow.models import CashCut, CashMovement, PaymentMethod
from apps.cashflow.services import (
    MATERIALS_EXPENSE_PREFIX,
    close_cash_cut,
    compute_cash_box,
    compute_cash_box_detail,
    compute_outflows,
    is_frank_daily_expense,
    is_materials_expense,
    looks_like_advance,
    summarize_outflows,
)
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

    def _pagar(self, payment_source='cash'):
        """Liquida al barbero. La fuente es obligatoria desde la fase 2: antes
        se asumía efectivo siempre y un pago por transferencia descuadraba la
        caja en ese monto."""
        self.client.force_login(self.frank_user)
        return self.client.post(
            reverse('cashflow_pay_barber_api', args=[self.barber.id]),
            data={'payment_source': payment_source},
            content_type='application/json',
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


class ConciliacionCajaTests(TestCase):
    """El "Debe haber" de la caja y la pantalla de Salidas cuentan lo mismo.

    Es la garantía de la que cuelga todo el arreglo: si algún día estas dos
    cifras dejan de coincidir, el dueño vuelve a ver plata que no puede
    reconstruir. La prueba arma un escenario con una salida de cada clase y
    verifica que los dos caminos den el mismo número.
    """

    def setUp(self):
        self.shop = Barbershop.objects.create(name='Área 30 Test')

        self.camilo = User.objects.create_user('camilo_conc', password='x')
        UserProfile.objects.create(user=self.camilo, role='superadmin',
                                   barbershop=self.shop)
        self.frank_user = User.objects.create_user('frank_conc', password='x')
        UserProfile.objects.create(user=self.frank_user, role='operational_admin',
                                   barbershop=self.shop)

        barber_user = User.objects.create_user('barbero_conc', password='x')
        self.barber = Barber.objects.create(
            user=barber_user, barbershop=self.shop, display_name='Carlos Conc',
            commission_percentage=Decimal('40.00'),
        )
        frank_barber_user = User.objects.create_user('frankb_conc', password='x')
        self.frank = Barber.objects.create(
            user=frank_barber_user, barbershop=self.shop, display_name='Franko Conc',
            commission_percentage=Decimal('50.00'),
        )

        self.efectivo, _ = PaymentMethod.objects.get_or_create(
            slug='efectivo', defaults={'name': 'Efectivo'})
        self.transferencia, _ = PaymentMethod.objects.get_or_create(
            slug='transferencia', defaults={'name': 'Transferencia'})

    def _escenario_completo(self):
        """Una salida de cada clase, en las dos cajas."""
        # Entradas, para que el saldo no sea absurdo.
        Sale.objects.create(barber=self.barber, base_price=Decimal('500000'),
                            payment_method=self.efectivo,
                            approval_status=Sale.STATUS_APPROVED)
        Sale.objects.create(barber=self.barber, base_price=Decimal('300000'),
                            payment_method=self.transferencia,
                            approval_status=Sale.STATUS_APPROVED)

        # Egresos de cada tipo y fuente.
        Expense.objects.create(description='Desinfectante', amount=Decimal('2450'),
                               expense_type='variable', payment_source='cash')
        Expense.objects.create(description='Arriendo', amount=Decimal('900000'),
                               expense_type='fixed', payment_source='transfer')
        Expense.objects.create(
            description=f'{MATERIALS_EXPENSE_PREFIX} Juanita (venta #911)',
            amount=Decimal('143000'), expense_type='materials',
            payment_source='cash')
        Expense.objects.create(
            description=f'{MATERIALS_EXPENSE_PREFIX} Vilma (venta #912)',
            amount=Decimal('30000'), expense_type='materials',
            payment_source='none')          # no pasó por caja: no debe contar
        Expense.objects.create(description='Pago Diario: Franko',
                               amount=Decimal('65000'),
                               expense_type='barber_payment', payment_source='cash')

        # Vales: uno con fuente y uno histórico sin fuente (no toca caja).
        BarberAdvance.objects.create(barber=self.frank, amount=Decimal('10000'),
                                     payment_source='cash')
        BarberAdvance.objects.create(barber=self.barber, amount=Decimal('15000'),
                                     payment_source='')

        # Liquidación a un barbero no-Frank, por transferencia.
        BarberPayment.objects.create(barber=self.barber, amount=Decimal('80000'),
                                     suggested_amount=Decimal('80000'),
                                     payment_source='transfer')

        # Movimientos manuales: un retiro y un traslado.
        CashMovement.objects.create(kind=CashMovement.KIND_WITHDRAWAL,
                                    source='cash', amount=Decimal('50000'),
                                    description='Retiro socio')
        CashMovement.objects.create(kind=CashMovement.KIND_TRANSFER,
                                    source='cash', to_source='transfer',
                                    amount=Decimal('20000'),
                                    description='Consignación')

    # ── El invariante ──────────────────────────────────────────────────

    def test_las_salidas_igualan_las_de_la_caja(self):
        self._escenario_completo()
        box = compute_cash_box()

        for fuente, clave in (('cash', 'cash_out'), ('transfer', 'transfer_out')):
            total = summarize_outflows(
                compute_outflows(source=fuente))['by_source'][fuente]
            self.assertEqual(
                total, box[clave],
                f'Las salidas listadas en {fuente} no cuadran con el control de caja.',
            )

    def test_el_detalle_de_la_caja_suma_lo_mismo_que_el_total(self):
        """La tarjeta muestra un total arriba y una lista abajo: deben coincidir."""
        self._escenario_completo()
        box = compute_cash_box()
        detalle = compute_cash_box_detail()

        self.assertEqual(Decimal(str(detalle['cash']['out_total'])), box['cash_out'])
        self.assertEqual(Decimal(str(detalle['transfer']['out_total'])),
                         box['transfer_out'])
        self.assertEqual(Decimal(str(detalle['cash']['balance'])), box['cash_balance'])

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_la_pantalla_de_salidas_muestra_el_mismo_total(self):
        self._escenario_completo()
        box = compute_cash_box()
        self.client.force_login(self.camilo)

        resp = self.client.get(reverse('admin_expenses'), {'period': 'caja'})
        self.assertEqual(resp.status_code, 200)
        summary = resp.context['summary']
        self.assertEqual(summary['by_source']['cash'], box['cash_out'])
        self.assertEqual(summary['by_source']['transfer'], box['transfer_out'])
        self.assertTrue(resp.context['cuadre']['ok'])

    def test_un_corte_arranca_el_periodo_de_cero(self):
        self._escenario_completo()
        saldo_antes = compute_cash_box()['cash_balance']

        # Se usa el servicio real: `close_cash_cut` es quien arrastra los
        # movimientos manuales al corte. Creando el CashCut a mano quedarían
        # sueltos y seguirían contando, que no es lo que pasa en producción.
        cut = close_cash_cut(user=self.camilo)
        self.assertIsNotNone(cut)

        # Todo lo anterior quedó del otro lado del corte.
        self.assertEqual(compute_outflows(), [])
        box = compute_cash_box()
        self.assertEqual(box['cash_out'], Decimal('0'))
        self.assertEqual(box['transfer_out'], Decimal('0'))
        # El saldo no se pierde: pasa a ser la apertura del período nuevo.
        self.assertEqual(box['cash_balance'], saldo_antes)

    # ── Las tres fugas ─────────────────────────────────────────────────

    def test_los_materiales_en_efectivo_restan_de_la_caja(self):
        """La fuga que más dinero costaba: la caja los excluía a propósito."""
        Expense.objects.create(
            description=f'{MATERIALS_EXPENSE_PREFIX} Juanita (venta #911)',
            amount=Decimal('143000'), expense_type='materials',
            payment_source='cash')
        self.assertEqual(compute_cash_box()['cash_out'], Decimal('143000'))

    def test_los_materiales_que_no_pasaron_por_caja_no_restan(self):
        Expense.objects.create(
            description=f'{MATERIALS_EXPENSE_PREFIX} Vilma (venta #912)',
            amount=Decimal('30000'), expense_type='materials',
            payment_source='none')
        box = compute_cash_box()
        self.assertEqual(box['cash_out'], Decimal('0'))
        self.assertEqual(box['transfer_out'], Decimal('0'))
        # Pero el egreso sí existe: es costo del servicio.
        self.assertEqual(Expense.objects.count(), 1)

    def test_un_egreso_que_parece_vale_se_rechaza(self):
        self.client.force_login(self.frank_user)
        for descripcion in ('Vale Franko', 'Adelanto a Carlos', 'Préstamo Vilma'):
            with self.subTest(descripcion=descripcion):
                resp = self.client.post(
                    reverse('admin_add_expense_api'),
                    data={'description': descripcion, 'amount': 20000},
                )
                self.assertEqual(resp.status_code, 400, resp.content)
                self.assertEqual(resp.json().get('code'), 'advance_like')
        self.assertEqual(Expense.objects.count(), 0)

    def test_un_egreso_normal_no_se_confunde_con_un_vale(self):
        """"Valentina" contiene "vale" pero no es un adelanto."""
        self.assertFalse(looks_like_advance('Compra a Valentina Distribuciones'))
        self.assertFalse(looks_like_advance('Desinfectante'))
        self.assertTrue(looks_like_advance('Vale Franko'))
        self.assertTrue(looks_like_advance('ADELANTO carlos'))

        self.client.force_login(self.frank_user)
        resp = self.client.post(
            reverse('admin_add_expense_api'),
            data={'description': 'Compra a Valentina Distribuciones', 'amount': 50000},
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_liquidar_por_transferencia_sale_de_la_caja_correcta(self):
        Commission.objects.create(
            sale=Sale.objects.create(barber=self.barber, base_price=Decimal('200000'),
                                     approval_status=Sale.STATUS_APPROVED),
            barber=self.barber, percentage=Decimal('40.00'),
        )
        self.client.force_login(self.frank_user)
        resp = self.client.post(
            reverse('cashflow_pay_barber_api', args=[self.barber.id]),
            data={'payment_source': 'transfer'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        box = compute_cash_box()
        self.assertEqual(box['cash_out'], Decimal('0'))
        self.assertEqual(box['transfer_out'], Decimal('80000'))

    def test_el_pago_de_frank_no_se_cuenta_dos_veces_sin_su_enlace(self):
        """El no-doble-conteo no puede colgar de un solo campo.

        `BarberPayment.expense` es SET_NULL: si el egreso desapareciera, el pago
        quedaría suelto y la caja lo empezaría a restar además del egreso. El
        segundo criterio (`daily_close`) lo sujeta.
        """
        cierre = DailyClose.objects.create(date=date.today(), closed_by=self.camilo)
        Expense.objects.create(description='Pago Diario: Franko',
                               amount=Decimal('65000'),
                               expense_type='barber_payment',
                               payment_source='cash',
                               included_in_daily_close=cierre)
        # El pago sin enlace al egreso: el caso que rompía la cuenta.
        BarberPayment.objects.create(barber=self.frank, daily_close=cierre,
                                     expense=None, amount=Decimal('65000'),
                                     suggested_amount=Decimal('65000'),
                                     payment_source='cash')

        box = compute_cash_box()
        self.assertEqual(box['cash_out'], Decimal('65000'))
        salidas = compute_outflows(source='cash')
        self.assertEqual(len(salidas), 1)
        self.assertEqual(salidas[0]['kind'], 'expense')

    def test_un_pago_de_cierre_sin_su_egreso_si_cuenta_como_salida(self):
        """Caso real encontrado en producción (cierre del 15/09/2026).

        Alguien borró el egreso "Pago Diario: Franko" desde la pantalla de
        Egresos y el BarberPayment quedó como única constancia de esos
        $392.000. Excluir todo pago de cierre habría hecho desaparecer esa
        salida y el "Debe haber" habría subido sin que nadie entregara plata.
        """
        cierre = DailyClose.objects.create(date=date.today(), closed_by=self.camilo)
        # Sin egreso "Pago Diario": solo queda el pago.
        BarberPayment.objects.create(barber=self.frank, daily_close=cierre,
                                     expense=None, amount=Decimal('392000'),
                                     suggested_amount=Decimal('392000'),
                                     payment_source='transfer')

        box = compute_cash_box()
        self.assertEqual(box['transfer_out'], Decimal('392000'))

        salidas = compute_outflows(source='transfer')
        self.assertEqual(len(salidas), 1)
        self.assertEqual(salidas[0]['kind'], 'payment')

    def test_el_egreso_del_pago_diario_no_se_puede_borrar_suelto(self):
        """Borrarlo dejaría huérfano el pago y descuadraría el cierre."""
        cierre = DailyClose.objects.create(date=date.today(), closed_by=self.camilo)
        egreso = Expense.objects.create(description='Pago Diario: Franko',
                                        amount=Decimal('65000'),
                                        expense_type='barber_payment',
                                        payment_source='cash',
                                        included_in_daily_close=cierre)
        BarberPayment.objects.create(barber=self.frank, daily_close=cierre,
                                     expense=egreso, amount=Decimal('65000'),
                                     suggested_amount=Decimal('65000'),
                                     payment_source='cash')

        self.client.force_login(self.camilo)
        resp = self.client.delete(
            reverse('admin_delete_expense_api', args=[egreso.id]))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('cierre', resp.json()['error'].lower())
        self.assertTrue(Expense.objects.filter(pk=egreso.id).exists())

    def test_liquidar_sin_indicar_la_fuente_falla(self):
        Commission.objects.create(
            sale=Sale.objects.create(barber=self.barber, base_price=Decimal('200000'),
                                     approval_status=Sale.STATUS_APPROVED),
            barber=self.barber, percentage=Decimal('40.00'),
        )
        self.client.force_login(self.frank_user)
        resp = self.client.post(
            reverse('cashflow_pay_barber_api', args=[self.barber.id]))
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(BarberPayment.objects.exists())


class CategoriasDeEgresoTests(TestCase):
    """Los tipos nuevos: 'materials' y 'barber_payment'.

    Lo que se cuida aquí es que un tipo nuevo no haga DESAPARECER plata de un
    total: varios cálculos filtran por lista blanca de tipos.
    """

    def setUp(self):
        self.shop = Barbershop.objects.create(name='Área 30 Test')
        self.camilo = User.objects.create_user('camilo_cat', password='x')
        UserProfile.objects.create(user=self.camilo, role='superadmin',
                                   barbershop=self.shop)
        self.frank_user = User.objects.create_user('frank_cat', password='x')
        UserProfile.objects.create(user=self.frank_user, role='operational_admin',
                                   barbershop=self.shop)

    def test_reconoce_materiales_por_tipo_y_por_prefijo(self):
        por_tipo = Expense(description='Tinte suelto', expense_type='materials')
        por_prefijo = Expense(description=f'{MATERIALS_EXPENSE_PREFIX} Juan (venta #3)',
                              expense_type='variable')
        otro = Expense(description='Arriendo', expense_type='fixed')

        self.assertTrue(is_materials_expense(por_tipo))
        self.assertTrue(is_materials_expense(por_prefijo))
        self.assertFalse(is_materials_expense(otro))
        # La firma vieja (solo texto) sigue funcionando.
        self.assertTrue(is_materials_expense(f'{MATERIALS_EXPENSE_PREFIX} Juan'))
        self.assertFalse(is_materials_expense('Arriendo'))
        self.assertFalse(is_materials_expense(None))

    def test_solo_el_pago_automatico_de_frank_cuenta_como_del_sistema(self):
        """Un bono suelto también es 'barber_payment', pero es gasto real.

        Si se tratara como egreso del sistema, no se podría editar ni borrar, y
        antes de la corrección tampoco pesaba en el ROI.
        """
        self.assertTrue(is_frank_daily_expense(
            Expense(description='Pago Diario: Franko', expense_type='variable')))
        self.assertTrue(is_frank_daily_expense(
            Expense(description='Pago Diario: Franko', expense_type='barber_payment')))
        self.assertFalse(is_frank_daily_expense(
            Expense(description='Bono de fin de mes', expense_type='barber_payment')))
        self.assertFalse(is_frank_daily_expense(
            Expense(description='Arriendo', expense_type='fixed')))

    def test_el_roi_cuenta_materiales_y_no_duplica_el_pago_a_frank(self):
        from apps.roi.services import get_month_financials

        hoy = date.today()
        Expense.objects.create(description='Desinfectante', amount=Decimal('10000'),
                               expense_type='variable', date=hoy)
        Expense.objects.create(description='Tinte', amount=Decimal('50000'),
                               expense_type='materials', date=hoy)
        Expense.objects.create(description='Arriendo', amount=Decimal('900000'),
                               expense_type='fixed', date=hoy)
        Expense.objects.create(description='Pago Diario: Franko',
                               amount=Decimal('65000'),
                               expense_type='barber_payment', date=hoy)

        datos = get_month_financials(hoy.year, hoy.month)
        # Materiales SÍ es gasto operativo; el pago diario a Frank NO (su costo
        # ya viaja en la Commission al 50%).
        self.assertEqual(datos['total_operational_expenses'], Decimal('60000'))
        self.assertEqual(datos['total_fixed_expenses'], Decimal('900000'))

    def test_un_bono_a_un_barbero_si_pesa_en_el_roi(self):
        """Solo el pago AUTOMÁTICO de Frank sale del gasto operativo.

        Excluir la categoría entera dejaba los bonos fuera del neto sin que
        nadie lo notara, y los socios se repartían una utilidad inexistente.
        """
        from apps.roi.services import get_month_financials

        hoy = date.today()
        Expense.objects.create(description='Pago Diario: Franko',
                               amount=Decimal('65000'),
                               expense_type='barber_payment', date=hoy)
        Expense.objects.create(description='Bono de fin de mes a Carlos',
                               amount=Decimal('100000'),
                               expense_type='barber_payment', date=hoy)

        datos = get_month_financials(hoy.year, hoy.month)
        self.assertEqual(datos['total_operational_expenses'], Decimal('100000'))

    def test_nadie_puede_escribir_a_mano_la_descripcion_del_sistema(self):
        """Si se pudiera, ese monto saldría del neto sin dejar rastro."""
        self.client.force_login(self.camilo)
        for descripcion in ('Pago Diario: Franko', 'Tinte (venta #99)'):
            with self.subTest(descripcion=descripcion):
                resp = self.client.post(reverse('admin_add_expense_api'), data={
                    'description': descripcion, 'amount': 50000,
                })
                self.assertEqual(resp.status_code, 400, resp.content)
                self.assertIn('reservado', resp.json()['error'])
        self.assertEqual(Expense.objects.count(), 0)

    def test_frank_puede_registrar_materiales_pero_no_pagos_a_barberos(self):
        self.client.force_login(self.frank_user)

        ok = self.client.post(reverse('admin_add_expense_api'), data={
            'description': 'Tinte para color', 'amount': 30000,
            'expense_type': 'materials',
        })
        self.assertEqual(ok.status_code, 200, ok.content)

        prohibido = self.client.post(reverse('admin_add_expense_api'), data={
            'description': 'Bono de fin de mes', 'amount': 100000,
            'expense_type': 'barber_payment',
        })
        self.assertEqual(prohibido.status_code, 403)

        fuente_prohibida = self.client.post(reverse('admin_add_expense_api'), data={
            'description': 'Insumo prestado', 'amount': 5000,
            'expense_type': 'materials', 'payment_source': 'none',
        })
        self.assertEqual(fuente_prohibida.status_code, 403)

    def test_un_superadmin_si_puede_usar_los_tipos_reservados(self):
        self.client.force_login(self.camilo)
        resp = self.client.post(reverse('admin_add_expense_api'), data={
            'description': 'Bono de fin de mes', 'amount': 100000,
            'expense_type': 'barber_payment', 'payment_source': 'none',
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        egreso = Expense.objects.get()
        self.assertEqual(egreso.expense_type, 'barber_payment')
        self.assertEqual(egreso.payment_source, 'none')

    def test_el_reporte_mensual_desglosa_los_egresos_por_categoria(self):
        """Es la pregunta que el dueño hace cada mes: cuánto en materiales,
        cuánto en el día a día, cuánto en pagarle a los barberos.
        """
        hoy = date.today()
        Expense.objects.create(description='Desinfectante', amount=Decimal('50000'),
                               expense_type='variable', date=hoy)
        Expense.objects.create(description='Tinte', amount=Decimal('171000'),
                               expense_type='materials', date=hoy)
        Expense.objects.create(description='Pago Diario: Franko',
                               amount=Decimal('65000'),
                               expense_type='barber_payment', date=hoy)

        self.client.force_login(self.camilo)
        resp = self.client.get(reverse('admin_monthly_report'),
                               {'year': hoy.year, 'month': hoy.month})
        self.assertEqual(resp.status_code, 200, resp.content)

        por_key = {d['key']: d['amount'] for d in resp.json()['expenses_by_type']}
        self.assertEqual(por_key['materials'], 171000.0)
        self.assertEqual(por_key['barber_payment'], 65000.0)
        self.assertEqual(por_key['variable'], 50000.0)
        # El desglose tiene que sumar exactamente el total de egresos: si una
        # categoría nueva no entrara, el dueño vería menos de lo que gastó.
        self.assertEqual(sum(por_key.values()), 286000.0)

    def test_la_migracion_reclasifica_los_egresos_viejos(self):
        """El backfill de cashflow.0017, que seed.py repite en cada arranque."""
        Expense.objects.create(
            description=f'{MATERIALS_EXPENSE_PREFIX} Juan (venta #1)',
            amount=Decimal('20000'), expense_type='variable')
        Expense.objects.create(description='Pago Diario: Franko',
                               amount=Decimal('65000'), expense_type='variable')

        Expense.objects.filter(
            description__startswith=MATERIALS_EXPENSE_PREFIX
        ).exclude(expense_type='materials').update(expense_type='materials')
        Expense.objects.filter(
            description__startswith='Pago Diario: Franko'
        ).exclude(expense_type='barber_payment').update(expense_type='barber_payment')

        self.assertEqual(
            Expense.objects.filter(expense_type='materials').count(), 1)
        self.assertEqual(
            Expense.objects.filter(expense_type='barber_payment').count(), 1)


class RegresionesDeLaRevisionTests(TestCase):
    """Cada prueba de aquí corresponde a un defecto que se encontró revisando
    el cambio, no a un requisito del plan. Están juntas a propósito: son los
    puntos donde el arreglo estuvo a punto de romper otra cosa.
    """

    def setUp(self):
        self.shop = Barbershop.objects.create(name='Área 30 Test')
        self.camilo = User.objects.create_user('camilo_reg', password='x')
        UserProfile.objects.create(user=self.camilo, role='superadmin',
                                   barbershop=self.shop)
        self.frank_user = User.objects.create_user('frank_reg', password='x')
        UserProfile.objects.create(user=self.frank_user, role='operational_admin',
                                   barbershop=self.shop)
        bu = User.objects.create_user('barbero_reg', password='x')
        self.barber = Barber.objects.create(
            user=bu, barbershop=self.shop, display_name='Carlos Reg',
            commission_percentage=Decimal('40.00'))
        fb = User.objects.create_user('frankb_reg', password='x')
        self.frank = Barber.objects.create(
            user=fb, barbershop=self.shop, display_name='Franko Reg',
            commission_percentage=Decimal('50.00'))

    # ── A. Los retiros no pueden desaparecer al cerrar un corte ────────

    def test_un_retiro_archivado_sigue_apareciendo_por_fecha(self):
        """Antes se filtraba por corte SIEMPRE, no solo dentro del período.

        El resultado era que un retiro dejaba de existir apenas se cerraba un
        corte: buscar "esta semana" mostraba los egresos pero ningún retiro, y
        el total le volvía a faltar plata al dueño.
        """
        CashMovement.objects.create(kind=CashMovement.KIND_WITHDRAWAL,
                                    source='cash', amount=Decimal('1000000'),
                                    description='Retiro socios')
        Expense.objects.create(description='Arriendo', amount=Decimal('800000'),
                               expense_type='fixed', payment_source='cash')
        hoy = timezone.localdate()

        # Antes del corte los dos aparecen.
        previo = compute_outflows(use_cash_period=False, date_from=hoy, date_to=hoy)
        self.assertEqual(len(previo), 2)

        close_cash_cut(user=self.camilo)

        # Después del corte, el período de caja arranca vacío...
        self.assertEqual(compute_outflows(), [])
        # ...pero buscar por fecha debe seguir mostrando los dos.
        posterior = compute_outflows(use_cash_period=False, date_from=hoy, date_to=hoy)
        self.assertEqual(len(posterior), 2, [r['label'] for r in posterior])
        total = summarize_outflows(posterior)['total']
        self.assertEqual(total, Decimal('1800000'))

    # ── B. El total mostrado es el de las filas mostradas ──────────────

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_en_ultimas_50_el_total_es_el_de_lo_que_se_ve(self):
        for i in range(60):
            Expense.objects.create(description=f'Gasto {i}', amount=Decimal('10000'),
                                   expense_type='variable', payment_source='cash')
        self.client.force_login(self.camilo)
        resp = self.client.get(reverse('admin_expenses'), {'period': 'recientes'})
        self.assertEqual(resp.status_code, 200)

        filas = resp.context['rows']
        self.assertEqual(len(filas), 50)
        suma_filas = sum(f['amount'] for f in filas)
        self.assertEqual(resp.context['summary']['total'], suma_filas)

    # ── C. Borrar un cierre no puede llevarse un bono manual ───────────

    def test_borrar_un_cierre_no_elimina_un_bono_registrado_a_mano(self):
        """Un bono también es 'barber_payment', pero nadie lo recrea al recerrar.

        Filtrar por el tipo lo borraba sin dejar rastro: plata desaparecida.
        """
        cierre = DailyClose.objects.create(date=date.today(), closed_by=self.camilo)
        automatico = Expense.objects.create(
            description='Pago Diario: Franko', amount=Decimal('65000'),
            expense_type='barber_payment', payment_source='cash',
            included_in_daily_close=cierre)
        bono = Expense.objects.create(
            description='Bono de fin de mes a Carlos', amount=Decimal('100000'),
            expense_type='barber_payment', payment_source='cash',
            included_in_daily_close=cierre)

        self.client.force_login(self.camilo)
        resp = self.client.delete(
            reverse('admin_delete_daily_close_api', args=[cierre.id]))
        self.assertEqual(resp.status_code, 200, resp.content)

        self.assertFalse(Expense.objects.filter(pk=automatico.id).exists())
        self.assertTrue(Expense.objects.filter(pk=bono.id).exists())

    # ── D. El candado es para los egresos del sistema, no para el tipo ──

    def test_un_egreso_de_materiales_hecho_a_mano_se_puede_editar(self):
        automatico = Expense.objects.create(
            description=f'{MATERIALS_EXPENSE_PREFIX} Juanita (venta #911)',
            amount=Decimal('143000'), expense_type='materials',
            payment_source='cash')
        manual = Expense.objects.create(
            description='Tinte comprado en la droguería', amount=Decimal('30000'),
            expense_type='materials', payment_source='cash')

        por_id = {r['id']: r for r in compute_outflows() if r['kind'] == 'expense'}
        self.assertTrue(por_id[automatico.id]['is_system'])
        self.assertFalse(por_id[manual.id]['is_system'])

    # ── E. Un egreso viejo con la palabra "vale" se puede corregir ─────

    def test_se_puede_editar_un_egreso_que_ya_traia_la_palabra_vale(self):
        """Si no, los que hay que arreglar quedan congelados justamente."""
        viejo = Expense.objects.create(description='Vale Franko',
                                       amount=Decimal('20000'),
                                       expense_type='variable',
                                       payment_source='cash')
        self.client.force_login(self.camilo)

        # Cambiar solo las notas, sin tocar la descripción: debe dejar.
        ok = self.client.post(reverse('admin_edit_expense_api', args=[viejo.id]),
                              data={'notes': 'Pendiente de convertir en vale real'})
        self.assertEqual(ok.status_code, 200, ok.content)

        # Pero renombrar OTRO egreso para que parezca vale sigue prohibido.
        otro = Expense.objects.create(description='Desinfectante',
                                      amount=Decimal('2450'),
                                      expense_type='variable',
                                      payment_source='cash')
        no = self.client.post(reverse('admin_edit_expense_api', args=[otro.id]),
                              data={'description': 'Adelanto a Carlos'})
        self.assertEqual(no.status_code, 400)
        self.assertEqual(no.json().get('code'), 'advance_like')

    # ── F. La pantalla del barbero manda la fuente ─────────────────────

    def test_la_pantalla_del_barbero_manda_la_fuente_al_liquidar(self):
        """El endpoint la exige; si esa plantilla no la manda, queda rota."""
        html = io.open(
            'templates/barberos/pagos_vales.html', encoding='utf-8').read()
        self.assertIn('payment_source', html)
        self.assertIn("'Content-Type': 'application/json'", html)
