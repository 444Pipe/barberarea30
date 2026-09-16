"""Audita el control de caja y explica el descuadre contra la pagina de Egresos.

Motivacion (ver PLAN_CONCILIACION_CAJA.md, fase 1): el dueno reporta que el
"Debe haber" de la tarjeta de Efectivo no coincide con lo que puede reconstruir
en /admin-panel/expenses/. No es un error de suma: cada pantalla suma una lista
distinta, y ademas hay salidas de dinero que la caja excluye a proposito.

Este comando NO ESCRIBE NADA. Solo lee y reporta:

  1. Periodo de caja en curso (desde el ultimo corte) y su apertura.
  2. La caja tal como la calcula hoy `compute_cash_box()`.
  3. Egresos de materiales que la caja excluye pero Egresos si muestra.
  4. Egresos cuya descripcion parece un vale/adelanto (no bajan el saldo del
     barbero: el cierre le sugiere pagarle completo -> doble entrega).
  5. Liquidaciones a barberos no-Frank que quedaron con la fuente por defecto.
  6. Egresos cuya fecha visible no es la de registro (la caja acota por
     `created_at`, la pagina de Egresos filtra por `date`).
  7. Cuanto va a cambiar el "Debe haber" al desplegar el arreglo.

Uso:

    python manage.py audit_cash_box
    python manage.py audit_cash_box --all          # diagnostico sobre todo el historico
    python manage.py audit_cash_box --json         # salida para adjuntar/archivar
    python manage.py audit_cash_box --limit 50     # mas filas por seccion
"""

import json
import re
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.cashflow import services as cashflow_services
from apps.cashflow.models import (
    BarberAdvance, BarberPayment, CashMovement, Expense,
)


# Un egreso cuya descripcion contiene alguna de estas palabras es, casi seguro,
# un adelanto a un barbero escrito a mano en vez de usar el boton "Dar vale".
# Sale de la caja pero no baja el saldo del barbero -> se paga dos veces.
ADVANCE_LIKE_RE = re.compile(
    r'(?i)\b(vale|vales|adelanto|adelantos|anticipo|anticipos|pr[eé]stamo|prestamo|prestamos)\b'
)

FRANK_DAILY_PREFIX = 'Pago Diario: Franko'


def _money(value):
    """Formato COP sin centavos, con separador de miles."""
    return f'${Decimal(value or 0):,.0f}'


def _f(value):
    return float(Decimal(value or 0))


def _source_label(source):
    return {
        'cash': 'Efectivo',
        'transfer': 'Transferencia',
        'none': 'No salio de caja',
        '': '(sin fuente)',
        None: '(sin fuente)',
    }.get(source, source)


class Command(BaseCommand):
    help = ('Audita el control de caja: explica la diferencia entre el "Debe haber" '
            'y la pagina de Egresos. Solo lectura.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--all', action='store_true', dest='all_history',
            help='Diagnostica sobre todo el historico, no solo el periodo de caja en curso.',
        )
        parser.add_argument(
            '--json', action='store_true', dest='as_json',
            help='Imprime el reporte en JSON (para adjuntarlo o archivarlo).',
        )
        parser.add_argument(
            '--limit', type=int, default=25,
            help='Maximo de filas a listar por seccion en la salida de texto. Default 25.',
        )

    # ── helpers de acotacion ────────────────────────────────────────────

    def _since(self, qs, period_start, field='created_at'):
        if period_start is None or self.all_history:
            return qs
        return qs.filter(**{f'{field}__gt': period_start})

    # ── recoleccion ─────────────────────────────────────────────────────

    def _collect(self, period_start):
        """Arma el reporte completo en un dict serializable."""
        cut = cashflow_services.current_cash_cut()
        box = cashflow_services.compute_cash_box()

        # ── 3. Materiales excluidos de la caja ──────────────────────────
        materials_qs = self._since(
            Expense.objects.filter(
                description__startswith=cashflow_services.MATERIALS_EXPENSE_PREFIX
            ).select_related('registered_by', 'included_in_daily_close'),
            period_start,
        ).order_by('-created_at')

        materials = []
        materials_by_source = {'cash': Decimal('0'), 'transfer': Decimal('0'), 'otro': Decimal('0')}
        for e in materials_qs:
            bucket = e.payment_source if e.payment_source in ('cash', 'transfer') else 'otro'
            materials_by_source[bucket] += Decimal(e.amount)
            materials.append({
                'id': e.id,
                'descripcion': e.description,
                'monto': _f(e.amount),
                'fuente': e.payment_source,
                'fuente_label': _source_label(e.payment_source),
                'fecha': e.date.isoformat(),
                'registrado': timezone.localtime(e.created_at).isoformat(),
                'registrado_por': (
                    e.registered_by.get_full_name() or e.registered_by.username
                ) if e.registered_by else 'Sistema',
                'en_cierre': e.included_in_daily_close_id,
            })

        # ── 4. Egresos que parecen un vale ──────────────────────────────
        advance_like_qs = self._since(
            Expense.objects.exclude(
                description__startswith=cashflow_services.MATERIALS_EXPENSE_PREFIX
            ).exclude(
                description__startswith=FRANK_DAILY_PREFIX
            ).select_related('registered_by', 'included_in_daily_close'),
            period_start,
        ).order_by('-created_at')

        advance_like = []
        advance_like_total = Decimal('0')
        for e in advance_like_qs:
            if not ADVANCE_LIKE_RE.search(e.description or ''):
                continue
            advance_like_total += Decimal(e.amount)
            advance_like.append({
                'id': e.id,
                'descripcion': e.description,
                'monto': _f(e.amount),
                'fuente': e.payment_source,
                'fuente_label': _source_label(e.payment_source),
                'tipo': e.expense_type,
                'fecha': e.date.isoformat(),
                'registrado': timezone.localtime(e.created_at).isoformat(),
                'registrado_por': (
                    e.registered_by.get_full_name() or e.registered_by.username
                ) if e.registered_by else 'Sistema',
                'en_cierre': e.included_in_daily_close_id,
                'notas': e.notes or '',
            })

        # ── 5. Liquidaciones no-Frank y su fuente ───────────────────────
        payments_qs = self._since(
            BarberPayment.objects.filter(daily_close__isnull=True)
            .select_related('barber', 'created_by'),
            period_start,
        ).order_by('-created_at')

        payments = []
        payments_by_source = {'cash': Decimal('0'), 'transfer': Decimal('0')}
        for p in payments_qs:
            if p.payment_source in payments_by_source:
                payments_by_source[p.payment_source] += Decimal(p.amount)
            payments.append({
                'id': p.id,
                'barbero': p.barber.display_name if p.barber else '?',
                'monto': _f(p.amount),
                'fuente': p.payment_source,
                'fuente_label': _source_label(p.payment_source),
                'registrado': timezone.localtime(p.created_at).isoformat(),
                'registrado_por': (
                    p.created_by.get_full_name() or p.created_by.username
                ) if p.created_by else 'Sistema',
                'notas': p.notes or '',
                # Un pago enlazado a un Expense es el de Frank: la caja lo omite
                # para no contarlo dos veces.
                'ligado_a_egreso': p.expense_id,
            })

        # ── Vales del sistema (para contraste) ──────────────────────────
        advances_qs = self._since(
            BarberAdvance.objects.select_related('barber', 'created_by'),
            period_start,
        ).order_by('-created_at')

        advances = []
        advances_by_source = {'cash': Decimal('0'), 'transfer': Decimal('0'), 'sin_fuente': Decimal('0')}
        for a in advances_qs:
            bucket = a.payment_source if a.payment_source in ('cash', 'transfer') else 'sin_fuente'
            advances_by_source[bucket] += Decimal(a.amount)
            advances.append({
                'id': a.id,
                'barbero': a.barber.display_name if a.barber else '?',
                'monto': _f(a.amount),
                'fuente': a.payment_source,
                'fuente_label': _source_label(a.payment_source),
                'motivo': a.reason or '',
                'liquidado': a.is_settled,
                'registrado': timezone.localtime(a.created_at).isoformat(),
            })

        # ── 6. Egresos cuya fecha visible no es la de registro ──────────
        date_mismatch = []
        mismatch_qs = self._since(
            Expense.objects.select_related('registered_by'), period_start,
        ).order_by('-created_at')
        for e in mismatch_qs:
            registrado = timezone.localtime(e.created_at).date()
            if e.date == registrado:
                continue
            date_mismatch.append({
                'id': e.id,
                'descripcion': e.description,
                'monto': _f(e.amount),
                'fecha_egreso': e.date.isoformat(),
                'fecha_registro': registrado.isoformat(),
                'dias': (registrado - e.date).days,
            })

        # ── Pagos de Frank sin enlace a su egreso ───────────────────────
        # Si un pago de cierre perdio (o nunca tuvo) el enlace a su Expense, la
        # caja podria restarlo ademas del egreso: el pago diario descontado dos
        # veces. seed.py los re-enlaza en cada arranque; esto los lista para
        # poder confirmarlo.
        huerfanos = []
        for p in BarberPayment.objects.filter(
            daily_close__isnull=False, expense__isnull=True
        ).select_related('barber', 'daily_close'):
            huerfanos.append({
                'id': p.id,
                'barbero': p.barber.display_name if p.barber else '?',
                'monto': _f(p.amount),
                'cierre': p.daily_close.date.isoformat() if p.daily_close else None,
                'notas': p.notes or '',
            })

        # ── Movimientos manuales del periodo ────────────────────────────
        movements = []
        for m in CashMovement.objects.filter(cash_cut__isnull=True).select_related('created_by'):
            movements.append({
                'id': m.id,
                'tipo': m.get_kind_display(),
                'descripcion': m.description or '',
                'monto': _f(m.amount),
                'origen': _source_label(m.source),
                'destino': _source_label(m.to_source) if m.to_source else None,
                'efecto_efectivo': _f(m.effect_on('cash')),
                'efecto_transferencia': _f(m.effect_on('transfer')),
                'registrado': timezone.localtime(m.created_at).isoformat(),
            })

        # ── 7. Verificacion: los materiales ya estan dentro ─────────────
        # Desde la fase 2 `compute_cash_box` SI resta los materiales que
        # salieron de la caja. Aqui no se corrige nada: solo se separa cuanto
        # de las salidas actuales corresponde a materiales, para poder
        # confirmar que el ajuste quedo aplicado. Sumarlos de nuevo los
        # descontaria dos veces y reportaria un "Debe haber" mas bajo del real.
        period_materials = Expense.objects.filter(
            description__startswith=cashflow_services.MATERIALS_EXPENSE_PREFIX
        )
        if period_start is not None:
            period_materials = period_materials.filter(created_at__gt=period_start)

        mat_cash = Decimal('0')
        mat_transfer = Decimal('0')
        for e in period_materials:
            if e.payment_source == 'transfer':
                mat_transfer += Decimal(e.amount)
            elif e.payment_source == 'cash':
                mat_cash += Decimal(e.amount)

        # Si el total de materiales cabe dentro de las salidas, es que la
        # fase 2 esta aplicada. Si las salidas fueran MENORES, seria senal de
        # que la caja los sigue excluyendo.
        # Lo que la pantalla de produccion muestra HOY, si todavia corre el
        # codigo viejo: ese excluia los materiales de las salidas, asi que su
        # saldo es el de aqui MAS los materiales que ahora si se restan.
        corrected = {
            'materiales_en_efectivo': _f(mat_cash),
            'materiales_en_transferencia': _f(mat_transfer),
            'ya_incluidos_efectivo': Decimal(box['cash_out']) >= mat_cash,
            'ya_incluidos_transferencia': Decimal(box['transfer_out']) >= mat_transfer,
            # Antes de desplegar (codigo viejo en produccion)
            'antes_saldo_efectivo': _f(Decimal(box['cash_balance']) + mat_cash),
            'antes_saldo_transferencia': _f(Decimal(box['transfer_balance']) + mat_transfer),
            'antes_salidas_efectivo': _f(Decimal(box['cash_out']) - mat_cash),
            'antes_salidas_transferencia': _f(Decimal(box['transfer_out']) - mat_transfer),
            # Despues de desplegar (este codigo)
            'despues_saldo_efectivo': _f(box['cash_balance']),
            'despues_saldo_transferencia': _f(box['transfer_balance']),
        }

        return {
            'generado': timezone.localtime(timezone.now()).isoformat(),
            'alcance': 'todo el historico' if self.all_history else 'periodo de caja en curso',
            'periodo': {
                'inicio': timezone.localtime(period_start).isoformat() if period_start else None,
                'inicio_label': (
                    timezone.localtime(period_start).strftime('%d/%m/%Y %I:%M %p')
                    if period_start else 'sin cortes previos (todo el historico)'
                ),
                'ultimo_corte': {
                    'id': cut.id,
                    'cerrado': timezone.localtime(cut.closed_at).strftime('%d/%m/%Y %I:%M %p'),
                    'cerrado_por': (
                        cut.closed_by.get_full_name() or cut.closed_by.username
                    ) if cut.closed_by else '-',
                } if cut else None,
                'apertura_efectivo': _f(box['opening_cash']),
                'apertura_transferencia': _f(box['opening_transfer']),
            },
            'caja_actual': {
                'entradas_efectivo': _f(box['cash_income']),
                'salidas_efectivo': _f(box['cash_out']),
                'saldo_efectivo': _f(box['cash_balance']),
                'entradas_transferencia': _f(box['transfer_income']),
                'salidas_transferencia': _f(box['transfer_out']),
                'saldo_transferencia': _f(box['transfer_balance']),
            },
            'verificacion_materiales': corrected,
            'materiales_excluidos': {
                'filas': materials,
                'total_efectivo': _f(materials_by_source['cash']),
                'total_transferencia': _f(materials_by_source['transfer']),
                'total_otra_fuente': _f(materials_by_source['otro']),
            },
            'egresos_tipo_vale': {
                'filas': advance_like,
                'total': _f(advance_like_total),
            },
            'liquidaciones': {
                'filas': payments,
                'total_efectivo': _f(payments_by_source['cash']),
                'total_transferencia': _f(payments_by_source['transfer']),
            },
            'vales_del_sistema': {
                'filas': advances,
                'total_efectivo': _f(advances_by_source['cash']),
                'total_transferencia': _f(advances_by_source['transfer']),
                'total_sin_fuente': _f(advances_by_source['sin_fuente']),
            },
            'pagos_sin_enlace': huerfanos,
            'movimientos_manuales': movements,
            'egresos_fecha_desalineada': date_mismatch,
        }

    # ── salida de texto ─────────────────────────────────────────────────

    def _title(self, text):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(text))
        self.stdout.write('-' * len(text))

    def _render(self, r, limit):
        w = self.stdout.write

        w('')
        w(self.style.MIGRATE_HEADING('AUDITORIA DEL CONTROL DE CAJA - Area 30'))
        w(f"Generado: {r['generado']}")
        w(f"Alcance de los listados: {r['alcance']}")

        # 1. Periodo
        self._title('1. PERIODO DE CAJA')
        p = r['periodo']
        w(f"  Arranca: {p['inicio_label']}")
        if p['ultimo_corte']:
            c = p['ultimo_corte']
            w(f"  Ultimo corte: #{c['id']} el {c['cerrado']} por {c['cerrado_por']}")
        else:
            w('  Nunca se ha hecho un corte: el periodo abarca todo el historico.')
        w(f"  Apertura efectivo:      {_money(p['apertura_efectivo'])}")
        w(f"  Apertura transferencia: {_money(p['apertura_transferencia'])}")

        # 2. Caja actual
        self._title('2. CAJA TAL COMO LA MUESTRA HOY EL PANEL')
        c = r['caja_actual']
        w(f"  EFECTIVO       entradas {_money(c['entradas_efectivo']):>16}"
          f"   salidas {_money(c['salidas_efectivo']):>16}"
          f"   debe haber {_money(c['saldo_efectivo']):>16}")
        w(f"  TRANSFERENCIA  entradas {_money(c['entradas_transferencia']):>16}"
          f"   salidas {_money(c['salidas_transferencia']):>16}"
          f"   debe haber {_money(c['saldo_transferencia']):>16}")

        # 3. Materiales
        m = r['materiales_excluidos']
        self._title(f"3. MATERIALES DE SERVICIO ({len(m['filas'])} egresos)")
        w('  Insumos de un servicio (tinte, color). Los que salieron de una caja')
        w('  YA descuentan del "Debe haber" desde la fase 2. Los marcados como')
        w('  "No salio de caja" se registran pero no tocan el saldo.')
        w('')
        if not m['filas']:
            w('  (ninguno en este alcance)')
        for row in m['filas'][:limit]:
            marca = ' [en cierre]' if row['en_cierre'] else ''
            w(f"  {row['fecha']}  {_money(row['monto']):>14}  {row['fuente_label']:<18}"
              f"  {row['descripcion'][:60]}{marca}")
        if len(m['filas']) > limit:
            w(f"  ... y {len(m['filas']) - limit} mas (usa --limit para verlos)")
        w('')
        w(f"  Total en efectivo:       {_money(m['total_efectivo'])}")
        w(f"  Total en transferencia:  {_money(m['total_transferencia'])}")
        if m['total_otra_fuente']:
            w(f"  Total con otra fuente:   {_money(m['total_otra_fuente'])}")

        # 4. Egresos tipo vale
        v = r['egresos_tipo_vale']
        self._title(f"4. EGRESOS QUE PARECEN UN VALE ({len(v['filas'])} egresos)")
        w('  Adelantos escritos a mano como egreso en vez de usar "Dar vale".')
        w('  Salen de la caja pero NO bajan el saldo del barbero: el cierre le')
        w('  sugiere pagarle completo y la plata se entrega dos veces.')
        w('')
        if not v['filas']:
            w('  (ninguno en este alcance)')
        for row in v['filas'][:limit]:
            marca = ' [en cierre]' if row['en_cierre'] else ''
            w(f"  #{row['id']:<5} {row['fecha']}  {_money(row['monto']):>14}  "
              f"{row['fuente_label']:<18} {row['descripcion'][:45]:<45} "
              f"por {row['registrado_por']}{marca}")
        if len(v['filas']) > limit:
            w(f"  ... y {len(v['filas']) - limit} mas")
        w('')
        w(f"  Total: {_money(v['total'])}")
        if v['filas']:
            w('')
            w(self.style.WARNING(
                '  ACCION: confirmar con el dueno cuales de estos son adelantos reales.'))
            w('  Los aprobados se convierten con:')
            w('    python manage.py convert_expense_to_advance --expense-id <id> --barber-id <id>')

        # 5. Liquidaciones
        li = r['liquidaciones']
        self._title(f"5. LIQUIDACIONES A BARBEROS ({len(li['filas'])} pagos)")
        w('  Hoy pay_barber_view no pregunta la fuente: todas quedan en efectivo.')
        w('  Si alguna se pago por transferencia, el efectivo esta descuadrado.')
        w('')
        if not li['filas']:
            w('  (ninguna en este alcance)')
        for row in li['filas'][:limit]:
            ligado = ' [ligado a egreso: la caja lo omite]' if row['ligado_a_egreso'] else ''
            w(f"  #{row['id']:<5} {row['registrado'][:16]}  {_money(row['monto']):>14}  "
              f"{row['fuente_label']:<18} {row['barbero']:<20} por {row['registrado_por']}{ligado}")
        if len(li['filas']) > limit:
            w(f"  ... y {len(li['filas']) - limit} mas")
        w('')
        w(f"  Total cargado a efectivo:      {_money(li['total_efectivo'])}")
        w(f"  Total cargado a transferencia: {_money(li['total_transferencia'])}")

        # Vales del sistema
        a = r['vales_del_sistema']
        self._title(f"6. VALES DEL SISTEMA ({len(a['filas'])} vales)")
        w('  Estos si bajan el saldo del barbero. Los que tienen fuente vacia son')
        w('  historicos (anteriores al 27/08/2026) y NO tocan la caja, por decision.')
        w('')
        for row in a['filas'][:limit]:
            estado = 'liquidado' if row['liquidado'] else 'pendiente'
            w(f"  #{row['id']:<5} {row['registrado'][:16]}  {_money(row['monto']):>14}  "
              f"{row['fuente_label']:<18} {row['barbero']:<20} {estado}")
        if len(a['filas']) > limit:
            w(f"  ... y {len(a['filas']) - limit} mas")
        w('')
        w(f"  Total en efectivo:      {_money(a['total_efectivo'])}")
        w(f"  Total en transferencia: {_money(a['total_transferencia'])}")
        w(f"  Total sin fuente (no tocan caja): {_money(a['total_sin_fuente'])}")

        # Pagos de Frank sin enlace
        hu = r['pagos_sin_enlace']
        if hu:
            self._title(f"6b. PAGOS DE CIERRE SIN ENLACE A SU EGRESO ({len(hu)})")
            w('  Un pago de cierre sin enlace a su egreso se puede contar dos veces')
            w('  en la caja. seed.py los re-enlaza en cada arranque del servidor.')
            w('')
            for row in hu[:limit]:
                w(f"  #{row['id']:<5} cierre {row['cierre']}  {_money(row['monto']):>14}  "
                  f"{row['barbero']:<20} {row['notas'][:40]}")

        # Movimientos manuales
        mv = r['movimientos_manuales']
        self._title(f"7. MOVIMIENTOS MANUALES DEL PERIODO ({len(mv)})")
        if not mv:
            w('  (ninguno)')
        for row in mv[:limit]:
            w(f"  #{row['id']:<5} {row['registrado'][:16]}  {_money(row['monto']):>14}  "
              f"{row['tipo']:<22} {row['descripcion'][:40]}")
            w(f"         efecto efectivo {_money(row['efecto_efectivo']):>14}"
              f"   efecto transferencia {_money(row['efecto_transferencia']):>14}")

        # Fechas desalineadas
        d = r['egresos_fecha_desalineada']
        self._title(f"8. EGRESOS CON FECHA DISTINTA A LA DE REGISTRO ({len(d)})")
        w('  La caja acota por fecha de REGISTRO; la pagina de Egresos filtra por')
        w('  la fecha del egreso. Estos pueden aparecer en una y no en la otra.')
        w('')
        if not d:
            w('  (ninguno)')
        for row in d[:limit]:
            w(f"  #{row['id']:<5} egreso {row['fecha_egreso']}  registrado {row['fecha_registro']}"
              f"  ({row['dias']:+d} dias)  {_money(row['monto']):>14}  {row['descripcion'][:45]}")
        if len(d) > limit:
            w(f"  ... y {len(d) - limit} mas")

        # 9. Conclusion
        co = r['verificacion_materiales']
        self._title('9. CUANTO VA A CAMBIAR EL "DEBE HABER"')
        w('  Esta es LA CIFRA para el dueno. Si todavia NO se ha desplegado el')
        w('  arreglo, la columna "hoy" es lo que el ve en pantalla en este momento')
        w('  y la columna "despues" es lo que vera al desplegar.')
        w('')
        w(f"  {'':<16}{'HOY (en pantalla)':>22}{'DESPUES':>22}{'CAMBIO':>18}")
        w(f"  {'EFECTIVO':<16}{_money(co['antes_saldo_efectivo']):>22}"
          f"{_money(co['despues_saldo_efectivo']):>22}"
          f"{'-' + _money(co['materiales_en_efectivo']):>18}")
        w(f"  {'TRANSFERENCIA':<16}{_money(co['antes_saldo_transferencia']):>22}"
          f"{_money(co['despues_saldo_transferencia']):>22}"
          f"{'-' + _money(co['materiales_en_transferencia']):>18}")
        w('')

        baja = co['materiales_en_efectivo'] + co['materiales_en_transferencia']
        if baja:
            w(self.style.WARNING(
                '  AVISARLE AL DUENO ANTES DE DESPLEGAR:'))
            w(self.style.WARNING(
                f"  el \"Debe haber\" en efectivo va a BAJAR {_money(co['materiales_en_efectivo'])}."))
            w('')
            w('  No es un error nuevo ni plata que se perdio: es el costo de los')
            w('  materiales de servicio que YA habia salido del cajon y que la caja')
            w('  no estaba restando. El numero nuevo es el que va a cuadrar con la')
            w('  plata fisica al contarla.')
        else:
            w('  No hubo materiales de servicio en este periodo: el saldo no cambia.')

        if not (co['ya_incluidos_efectivo'] and co['ya_incluidos_transferencia']):
            w('')
            w(self.style.ERROR(
                '  ALERTA: las salidas son menores que los materiales del periodo.'))
            w(self.style.ERROR(
                '  Algo no cuadra en el calculo. Revisar compute_cash_box antes de seguir.'))

        w('')
        w('  Despues de desplegar: cuenten el efectivo fisico y comparenlo con el')
        w('  "Debe haber". Si no coincide, la pantalla de Salidas de Dinero')
        w('  (filtro "Periodo de caja") lista cada peso que salio.')
        w('')

    # ── entrada ─────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        self.all_history = options['all_history']
        limit = max(1, options['limit'])

        period_start, _opening_cash, _opening_transfer = cashflow_services.cash_period_bounds()
        report = self._collect(period_start)

        if options['as_json']:
            self.stdout.write(json.dumps(report, indent=2, ensure_ascii=False))
            return

        self._render(report, limit)
