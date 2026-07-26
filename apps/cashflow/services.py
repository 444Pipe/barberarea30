"""
cashflow/services.py
====================
Capa de lógica de negocio para el Checkout.

Centraliza la transacción completa de una venta:
  1. Crear Sale (Venta)
  2. Calcular y guardar Commission
  3. Descontar Inventario (InventoryMovement)
  4. Marcar Booking como completada
  5. Registrar en AuditLog (inmutable)

Toda la operación corre dentro de un bloque transaction.atomic(),
garantizando que o todo sucede o nada sucede (rollback automático).
"""
from decimal import Decimal
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.cashflow.models import Sale, Commission, PaymentMethod
from apps.inventory.models import ServiceInventoryItem, InventoryMovement
from apps.analytics.models import log_audit


# Prefijo del egreso que genera la casilla "Materiales" del checkout. Es un
# identificador semántico: los detalles de caja lo usan para separar el costo
# de materiales del resto de egresos (ver is_materials_expense).
MATERIALS_EXPENSE_PREFIX = 'Materiales Servicio:'


def is_materials_expense(description):
    """¿Este egreso es el costo de materiales de un servicio?

    Los materiales no son un gasto operativo más (arriendo, servicios): son el
    insumo de una venta concreta. Se separan en los detalles de caja para poder
    responder "¿de qué se compone este monto?" sin cambiar cómo se calculan los
    totales — sigue entrando en total_expenses como siempre.
    """
    return (description or '').startswith(MATERIALS_EXPENSE_PREFIX)


# La jornada no termina a la medianoche. Un cierre hecho a las 00:20 del
# domingo corresponde al sábado: antes se sellaba con la fecha del servidor y,
# como DailyClose.date es único, consumía el cupo del día siguiente y dejaba la
# caja bloqueada durante toda esa jornada.
BUSINESS_DAY_CUTOFF_HOUR = 5


def business_date(moment=None):
    """Jornada (fecha de negocio) a la que pertenece un instante.

    Entre medianoche y las 5 a.m. la jornada sigue siendo la del día anterior.
    """
    local = timezone.localtime(moment or timezone.now())
    if local.hour < BUSINESS_DAY_CUTOFF_HOUR:
        return (local - timedelta(days=1)).date()
    return local.date()


def close_blockers(target_date=None, relaxed=False):
    """Motivos por los que el cierre de caja de `target_date` no se puede hacer.

    Devuelve una lista de dicts `{code, message, count, severity}`. `severity`
    es `'block'` (impide cerrar) o `'warn'` (solo advierte). La usan el preview
    —para explicarlo en el modal— y el propio cierre, de modo que la UI y el
    backend nunca discrepen sobre por qué está bloqueado.

    `relaxed=True` es el modo superadministrador: los socios cierran cuando
    quieran, así que todo lo que no sea una restricción real de base de datos
    baja a advertencia. `already_closed` NUNCA baja: `DailyClose.date` es único
    y el camino correcto es borrar el cierre previo.
    """
    from apps.cashflow.models import DailyClose, Expense, Sale, InventorySale

    blockers = []
    jornada = target_date or business_date()

    def _sev(hard=False):
        return 'block' if (hard or not relaxed) else 'warn'

    existing = DailyClose.objects.filter(date=jornada).first()
    if existing:
        blockers.append({
            'code': 'already_closed',
            'message': (
                f'La jornada del {jornada.strftime("%d/%m/%Y")} ya tiene cierre '
                f'(generado el {timezone.localtime(existing.closed_at).strftime("%d/%m/%Y %I:%M %p")}). '
                f'Si quedó mal, un superadministrador puede borrarlo desde el '
                f'historial de cierres y volver a cerrar.'
            ),
            'count': 1,
            'severity': _sev(hard=True),
        })

    unapproved = Sale.objects.filter(
        included_in_daily_close__isnull=True, approval_status=Sale.STATUS_PENDING
    ).count()
    if unapproved:
        blockers.append({
            'code': 'pending_approvals',
            'message': (
                f'Hay {unapproved} venta(s) esperando aprobación. '
                + ('Quedarán pendientes y entrarán en el siguiente cierre.'
                   if relaxed else
                   'Apruébalas o recházalas en la pestaña "Pendientes" antes de cerrar.')
            ),
            'count': unapproved,
            'severity': _sev(),
        })

    has_movements = (
        Sale.objects.filter(
            included_in_daily_close__isnull=True, approval_status=Sale.STATUS_APPROVED
        ).exists()
        or InventorySale.objects.filter(included_in_daily_close__isnull=True).exists()
        or Expense.objects.filter(included_in_daily_close__isnull=True).exists()
    )
    if not has_movements:
        blockers.append({
            'code': 'no_movements',
            'message': (
                'No hay ventas, productos ni egresos pendientes: el cierre quedaría en ceros.'
                if relaxed else
                'No hay ventas, productos ni egresos pendientes por cerrar.'
            ),
            'count': 0,
            'severity': _sev(),
        })

    return blockers


def recalculate_unpaid_commissions(barber, new_percentage, apply=False,
                                   since=None, until=None):
    """Recalcula al `new_percentage` las comisiones NO PAGADAS de un barbero.

    Nace de un caso real: la migración `barbers.0010` (01-may-2026) creó
    `Barber.commission_percentage` con default 40 y se lo puso a todos,
    incluido Frank, cuyo acuerdo es 50. La corrección del perfil llegó el
    10-jul, así que entre esas fechas se emitieron comisiones al 40%. Cambiar
    el perfil NO las arregla: `Commission.percentage` se congela en el momento
    del checkout.

    Reglas:
      - Solo toca `is_paid=False`. Lo ya liquidado no se reescribe: cambiar
        historia pagada descuadraría cierres y pagos ya entregados.
      - Solo sube porcentajes por debajo del objetivo; nunca baja uno que ya
        esté igual o por encima.
      - Usa `.update()` en vez de `save()` a propósito: `Commission.save()`
        recalcularía `basis_amount` desde la venta y borraría el ajuste manual
        de los servicios de Frank con materiales (ver `process_checkout`).
      - `since`/`until` acotan el período. Sin ellos toma todo el histórico,
        que casi nunca es lo que se quiere: los meses viejos suelen estar
        cubiertos aunque su bandera `is_paid` diga otra cosa.

    Con `apply=False` (default) no escribe nada: devuelve la simulación para
    poder revisarla antes de mover plata.
    """
    from apps.cashflow.models import Commission

    target = _to_decimal(new_percentage)
    pending = (
        Commission.objects
        .filter(barber=barber, is_paid=False, percentage__lt=target)
        .select_related('sale', 'sale__service')
        .order_by('created_at')
    )
    if since is not None:
        pending = pending.filter(created_at__gte=since)
    if until is not None:
        pending = pending.filter(created_at__lt=until)

    rows, before_total, after_total = [], Decimal('0'), Decimal('0')
    for comm in pending:
        new_amount = (comm.basis_amount * target) / Decimal('100.00')
        new_total = new_amount + comm.tip_amount
        before_total += comm.total_earnings
        after_total += new_total
        rows.append({
            'id': comm.id,
            'date': timezone.localtime(comm.created_at).strftime('%Y-%m-%d %I:%M %p'),
            'service': comm.sale.service.name if comm.sale and comm.sale.service else 'General',
            'basis_amount': float(comm.basis_amount),
            'old_percentage': float(comm.percentage),
            'old_commission': float(comm.commission_amount),
            'new_commission': float(new_amount),
            'difference': float(new_amount - comm.commission_amount),
        })

    if apply and rows:
        with transaction.atomic():
            for comm in pending:
                new_amount = (comm.basis_amount * target) / Decimal('100.00')
                Commission.objects.filter(id=comm.id).update(
                    percentage=target,
                    commission_amount=new_amount,
                    total_earnings=new_amount + comm.tip_amount,
                )

    return {
        'applied': bool(apply and rows),
        'barber': barber.display_name,
        'new_percentage': float(target),
        'count': len(rows),
        'earnings_before': float(before_total),
        'earnings_after': float(after_total),
        'difference': float(after_total - before_total),
        'rows': rows,
    }


def parse_close_date(raw, today=None):
    """Valida la fecha elegida para un cierre. Devuelve (fecha, error).

    Solo los superadministradores pueden elegirla; aquí se valida el formato y
    que no sea futura — sellar una jornada que aún no ocurrió quemaría el cupo
    de esa fecha (`DailyClose.date` es único).
    """
    from datetime import datetime as _dt

    try:
        parsed = _dt.strptime(str(raw).strip(), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None, 'Fecha de cierre inválida. Usa el formato AAAA-MM-DD.'

    limite = today or timezone.localtime().date()
    if parsed > limite:
        return None, (
            f'No se puede cerrar una fecha futura ({parsed.strftime("%d/%m/%Y")}). '
            f'Elige hoy o un día anterior.'
        )
    return parsed, None


def _to_decimal(value):
    """Convierte cualquier entrada (None, int, float, Decimal, str) a Decimal."""
    if value is None:
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def compute_live_net_income(*, service_revenue, inventory_revenue,
                            non_frank_commissions, real_expenses,
                            frank_commission=0):
    """Fórmula ÚNICA del Ingreso Neto (referencia: cierre diario).

    Se centraliza aquí para que el dashboard de caja, el detalle en vivo y el
    cierre diario produzcan SIEMPRE el mismo resultado.

    Neto = ingresos de servicios + ingresos de inventario
           − comisiones de los barberos NO-Frank
           − comisión de Frank (su propina es pass-through cliente→barbero,
             no es utilidad ni gasto real de la empresa, por eso NO entra)
           − egresos reales de la empresa (sin el componente de propina del
             pago automático a Frank).

    Todos los parámetros son montos ya agregados. `real_expenses` debe ser el
    gasto real de la empresa EXCLUYENDO tanto la comisión como la propina de
    Frank (es decir, sin el rubro "Pago Diario: Franko").
    """
    return (
        _to_decimal(service_revenue)
        + _to_decimal(inventory_revenue)
        - _to_decimal(non_frank_commissions)
        - _to_decimal(frank_commission)
        - _to_decimal(real_expenses)
    )


def get_frank_barber():
    """Único punto de identificación de Frank como barbero."""
    from apps.barbers.models import Barber
    return Barber.objects.filter(display_name__icontains='frank').first()


def compute_frank_ledger():
    """Saldo corriente de Frank, SIEMPRE derivado (nunca almacenado):

        saldo = Σ ganado (comisiones+propinas de ventas aprobadas, histórico)
              − Σ vales entregados (TODOS, liquidados o no)
              − Σ pagos reales hechos en cierres (BarberPayment)

    Positivo → la empresa le debe a Frank; negativo → Frank debe.
    `unpaid_earnings` / `unsettled_advances` son informativos para la UI
    (desglose del día); el saldo NO depende de los flags is_paid/is_settled.
    """
    from django.db.models import Sum
    from apps.cashflow.models import Commission, BarberAdvance, BarberPayment

    frank = get_frank_barber()
    zero = Decimal('0')
    if not frank:
        return {
            'exists': False, 'earnings_total': zero, 'advances_total': zero,
            'payments_total': zero, 'balance': zero, 'unpaid_earnings': zero,
            'unsettled_advances': zero, 'suggested_payment': zero,
        }

    frank_commissions = Commission.objects.filter(
        barber=frank, sale__approval_status=Sale.STATUS_APPROVED
    )
    earnings_total = frank_commissions.aggregate(t=Sum('total_earnings'))['t'] or zero
    advances_total = BarberAdvance.objects.filter(barber=frank).aggregate(
        t=Sum('amount'))['t'] or zero
    payments_total = BarberPayment.objects.filter(barber=frank).aggregate(
        t=Sum('amount'))['t'] or zero

    balance = _to_decimal(earnings_total) - _to_decimal(advances_total) - _to_decimal(payments_total)

    unpaid_earnings = frank_commissions.filter(is_paid=False).aggregate(
        t=Sum('total_earnings'))['t'] or zero
    unsettled_advances = BarberAdvance.objects.filter(
        barber=frank, is_settled=False).aggregate(t=Sum('amount'))['t'] or zero

    # Sugerido a pagar: SOLO lo pendiente de los últimos 30 días, para no arrastrar
    # backlog antiguo al cierre (los pagos "tomaban fechas anteriores"). La DEUDA
    # real (balance) se mantiene completa: nada se pierde, solo no se sugiere de una.
    WINDOW_DAYS = 30
    cutoff = timezone.now() - timedelta(days=WINDOW_DAYS)
    recent_unpaid = frank_commissions.filter(
        is_paid=False, created_at__gte=cutoff
    ).aggregate(t=Sum('total_earnings'))['t'] or zero
    recent_advances = BarberAdvance.objects.filter(
        barber=frank, is_settled=False, created_at__gte=cutoff
    ).aggregate(t=Sum('amount'))['t'] or zero
    suggested_30d = _to_decimal(recent_unpaid) - _to_decimal(recent_advances)
    # Nunca sugerir más que la deuda real, ni menos que cero.
    suggested = max(Decimal('0'), min(suggested_30d, max(balance, Decimal('0'))))

    return {
        'exists': True,
        'earnings_total': _to_decimal(earnings_total),
        'advances_total': _to_decimal(advances_total),
        'payments_total': _to_decimal(payments_total),
        'balance': balance,
        'unpaid_earnings': _to_decimal(unpaid_earnings),
        'unsettled_advances': _to_decimal(unsettled_advances),
        'unpaid_earnings_30d': _to_decimal(recent_unpaid),
        'suggested_window_days': WINDOW_DAYS,
        'suggested_payment': suggested,
    }


def current_cash_cut(exclude_id=None):
    """Último corte de caja, o None si nunca se ha cerrado.

    Marca el inicio del período en curso. Reemplaza al "día 1 del mes": el
    saldo de caja ya no se reinicia solo, lo cierran los socios cuando quieren.

    `exclude_id` permite preguntar "¿cuál sería el último corte SI borrara
    este?", que es como se simula una reversión sin escribir nada.

    El desempate por `-id` importa: `closed_at` es auto_now_add y dos cortes
    creados en el mismo instante dejarían el orden indefinido, y todo el
    invariante "solo se deshace el último" cuelga de este orden.
    """
    from apps.cashflow.models import CashCut
    qs = CashCut.objects.all()
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return qs.order_by('-closed_at', '-id').first()


def cash_period_bounds(exclude_cut_id=None):
    """(inicio, apertura_efectivo, apertura_transferencia) del período en curso.

    `inicio` es None cuando todavía no hay ningún corte: en ese caso el período
    abarca todo el histórico y arranca en $0. Los socios fijan el saldo real
    con un movimiento de ajuste.
    """
    cut = current_cash_cut(exclude_id=exclude_cut_id)
    if not cut:
        return None, Decimal('0'), Decimal('0')
    return cut.closed_at, _to_decimal(cut.opening_cash), _to_decimal(cut.opening_transfer)


def compute_cash_box(reference_date=None, exclude_cut_id=None):
    """Control de caja del PERÍODO EN CURSO, separado por efectivo y transferencia.

    El período va desde el último corte (`CashCut`) hasta ahora; si nunca se ha
    cerrado, abarca todo. Antes se recalculaba desde el día 1 del mes y el
    saldo se perdía cada 1° — ver `CashCut`.

    Para cada método (efectivo / transferencia):
      apertura = saldo con el que quedó el período anterior (0 si se retiró)
      ingresos = ventas de servicios (precio final + propina) + ventas de
                 inventario, sobre ventas APROBADAS del período
                 + inyecciones de capital y traslados entrantes
      salidas  = egresos reales (excluye el costo de materiales de servicios,
                 que es insumo de una venta, no un retiro de caja)
                 + pagos a barberos NO-Frank (los de Frank ya están
                 representados como egreso "Pago Diario", para no contar doble)
                 + retiros y traslados salientes
      saldo    = apertura + ingresos − salidas  → cuánto DEBE haber físicamente.

    Efectivo agrupa ventas sin método o con método 'efectivo' (paridad con el
    resto del módulo). Transferencia agrupa 'transferencia'.
    """
    from django.db.models import Q, Sum, F
    from apps.cashflow.models import (
        Sale, InventorySale, Expense, BarberPayment, CashMovement,
    )

    period_start, opening_cash, opening_transfer = cash_period_bounds(exclude_cut_id)
    zero = Decimal('0')

    approved = Sale.objects.filter(approval_status=Sale.STATUS_APPROVED)
    inv = InventorySale.objects.all()
    exp = Expense.objects.all()
    pays = BarberPayment.objects.all()
    # Al simular el borrado de un corte, sus movimientos archivados vuelven al
    # período: hay que contarlos igual que los sueltos.
    if exclude_cut_id is not None:
        movements = CashMovement.objects.filter(
            Q(cash_cut__isnull=True) | Q(cash_cut_id=exclude_cut_id)
        )
    else:
        movements = CashMovement.objects.filter(cash_cut__isnull=True)
    if period_start is not None:
        approved = approved.filter(created_at__gt=period_start)
        inv = inv.filter(created_at__gt=period_start)
        exp = exp.filter(created_at__gt=period_start)
        pays = pays.filter(created_at__gt=period_start)

    cash_q = Q(payment_method__isnull=True) | Q(payment_method__slug='efectivo')
    transfer_q = Q(payment_method__slug='transferencia')

    def income(method_q):
        s = approved.filter(method_q).aggregate(
            t=Sum(F('final_price') + F('tip_amount')))['t'] or zero
        i = inv.filter(method_q).aggregate(t=Sum('total_price'))['t'] or zero
        return _to_decimal(s) + _to_decimal(i)

    def outflow(source):
        e = exp.filter(payment_source=source).exclude(
            description__startswith=MATERIALS_EXPENSE_PREFIX
        ).aggregate(t=Sum('amount'))['t'] or zero
        p = pays.filter(payment_source=source, expense__isnull=True).aggregate(
            t=Sum('amount'))['t'] or zero
        return _to_decimal(e) + _to_decimal(p)

    # Movimientos manuales: se reparten entre entradas y salidas según su
    # efecto real sobre cada caja (un traslado sale de una y entra en la otra).
    manual = list(movements)

    def manual_in(box):
        return _to_decimal(sum(
            (m.effect_on(box) for m in manual if m.effect_on(box) > 0), zero
        ))

    def manual_out(box):
        return _to_decimal(sum(
            (-m.effect_on(box) for m in manual if m.effect_on(box) < 0), zero
        ))

    cash_income = income(cash_q) + manual_in('cash')
    transfer_income = income(transfer_q) + manual_in('transfer')
    cash_out = outflow('cash') + manual_out('cash')
    transfer_out = outflow('transfer') + manual_out('transfer')

    return {
        'period_start': period_start,
        'opening_cash': opening_cash,
        'opening_transfer': opening_transfer,
        'cash_income': cash_income,
        'transfer_income': transfer_income,
        'cash_out': cash_out,
        'transfer_out': transfer_out,
        'cash_balance': opening_cash + cash_income - cash_out,
        'transfer_balance': opening_transfer + transfer_income - transfer_out,
    }


def compute_cash_box_detail(reference_date=None):
    """Igual que compute_cash_box pero con el HISTORIAL desglosado de cada
    movimiento (entradas y salidas) por método, para mostrar de dónde sale y
    entra la plata en efectivo y en transferencia.
    """
    from django.db.models import Q
    from apps.cashflow.models import (
        Sale, InventorySale, Expense, BarberPayment, CashMovement,
    )

    period_start, opening_cash, opening_transfer = cash_period_bounds()
    zero = Decimal('0')

    cash_q = Q(payment_method__isnull=True) | Q(payment_method__slug='efectivo')
    transfer_q = Q(payment_method__slug='transferencia')

    def since(qs, field='created_at'):
        """Acota al período en curso. Sin corte previo, no acota nada."""
        return qs if period_start is None else qs.filter(**{f'{field}__gt': period_start})

    manual = list(since(CashMovement.objects.filter(cash_cut__isnull=True))
                  .select_related('created_by'))

    def build(method_q, source, opening):
        income, outflow = [], []

        # ── ENTRADAS ──────────────────────────────────────────────
        for s in since(Sale.objects.filter(
            approval_status=Sale.STATUS_APPROVED
        )).filter(method_q).select_related('booking', 'service'):
            amt = _to_decimal(s.final_price) + _to_decimal(s.tip_amount)
            if amt == 0:
                continue
            dt = timezone.localtime(s.created_at)
            income.append({
                '_k': dt.isoformat(),
                'date': dt.strftime('%d/%m'),
                'label': s.booking.client_name if s.booking else 'Venta',
                'sub': (s.service.name if s.service else 'Servicio') + (f' · propina ${s.tip_amount:,.0f}' if s.tip_amount else ''),
                'amount': float(amt),
            })
        for i in since(InventorySale.objects.all()).filter(method_q).select_related('item'):
            dt = timezone.localtime(i.created_at)
            income.append({
                '_k': dt.isoformat(),
                'date': dt.strftime('%d/%m'),
                'label': f'{i.quantity:g}x {i.item.name if i.item else "Producto"}',
                'sub': 'Producto',
                'amount': float(i.total_price),
            })

        # ── SALIDAS ───────────────────────────────────────────────
        for e in since(Expense.objects.filter(
            payment_source=source
        )).exclude(description__startswith=MATERIALS_EXPENSE_PREFIX):
            outflow.append({
                '_k': e.date.isoformat(),
                'date': e.date.strftime('%d/%m'),
                'label': e.description,
                'sub': e.get_expense_type_display(),
                'amount': float(e.amount),
            })
        for p in since(BarberPayment.objects.filter(
            payment_source=source, expense__isnull=True
        )).select_related('barber'):
            dt = timezone.localtime(p.created_at)
            outflow.append({
                '_k': dt.isoformat(),
                'date': dt.strftime('%d/%m'),
                'label': f'Pago a {p.barber.display_name if p.barber else "Barbero"}',
                'sub': 'Pago a barbero',
                'amount': float(p.amount),
            })

        # ── MOVIMIENTOS MANUALES (inyecciones, retiros, traslados) ────────
        # Van en el mismo historial que las ventas y los egresos: la idea es
        # poder responder "¿de dónde salió y a dónde se fue toda la plata?"
        # en una sola lista, sin tener que cruzar dos pantallas.
        for m in manual:
            effect = m.effect_on(source)
            if effect == 0:
                continue
            dt = timezone.localtime(m.created_at)
            quien = ''
            if m.created_by:
                quien = f' · {m.created_by.get_full_name() or m.created_by.username}'
            row = {
                '_k': dt.isoformat(),
                'date': dt.strftime('%d/%m'),
                'label': m.description or m.get_kind_display(),
                'sub': m.get_kind_display() + quien,
                'amount': float(abs(effect)),
                'is_manual': True,
            }
            (income if effect > 0 else outflow).append(row)

        income.sort(key=lambda x: x['_k'], reverse=True)
        outflow.sort(key=lambda x: x['_k'], reverse=True)
        for lst in (income, outflow):
            for it in lst:
                it.pop('_k', None)

        income_total = _to_decimal(sum(x['amount'] for x in income))
        out_total = _to_decimal(sum(x['amount'] for x in outflow))
        return {
            'income': income,
            'outflow': outflow,
            'income_total': income_total,
            'out_total': out_total,
            'opening': opening,
            'balance': opening + income_total - out_total,
        }

    cut = current_cash_cut()
    return {
        'period_start': period_start,
        'period_start_label': timezone.localtime(period_start).strftime('%d/%m/%Y %I:%M %p') if period_start else None,
        'last_cut': {
            'id': cut.id,
            'closed_at': timezone.localtime(cut.closed_at).strftime('%d/%m/%Y %I:%M %p'),
            'closed_by': (cut.closed_by.get_full_name() or cut.closed_by.username) if cut.closed_by else '—',
        } if cut else None,
        'cash': build(cash_q, 'cash', opening_cash),
        'transfer': build(transfer_q, 'transfer', opening_transfer),
    }


def register_cash_movement(*, kind, source, amount, description, user,
                           to_source=None):
    """Registra un movimiento manual de caja. Devuelve (movimiento, error).

    Valida aquí y no en la vista para que el comando, el endpoint y cualquier
    flujo futuro compartan las mismas reglas.
    """
    from apps.cashflow.models import CashMovement

    valid_kinds = dict(CashMovement.KINDS)
    if kind not in valid_kinds:
        return None, 'Tipo de movimiento inválido.'
    if source not in ('cash', 'transfer'):
        return None, 'Debes indicar si el movimiento es en efectivo o en transferencia.'

    amount = _to_decimal(amount)
    if kind == CashMovement.KIND_ADJUSTMENT:
        # El ajuste es la única operación con signo: refleja si el conteo real
        # quedó por encima o por debajo de lo que decía el sistema.
        if amount == 0:
            return None, 'El ajuste no puede ser cero: el saldo ya coincide.'
    else:
        if amount <= 0:
            return None, 'El monto debe ser mayor que cero.'

    if kind == CashMovement.KIND_TRANSFER:
        if to_source not in ('cash', 'transfer'):
            return None, 'Debes indicar a qué caja se traslada el dinero.'
        if to_source == source:
            return None, 'El origen y el destino del traslado no pueden ser la misma caja.'
    else:
        to_source = ''

    description = (description or '').strip() or valid_kinds[kind]

    movement = CashMovement.objects.create(
        kind=kind, source=source, to_source=to_source or '',
        amount=amount, description=description, created_by=user,
    )
    return movement, None


def close_cash_cut(*, user, withdraw_cash=False, withdraw_transfer=False, notes=''):
    """Cierra el período de caja y abre uno nuevo.

    Congela el saldo actual en un `CashCut`, archiva los movimientos manuales
    del período y decide con cuánto arranca el siguiente: $0 en las cajas de
    las que se retiró la plata, el saldo que traían en las demás.
    """
    from apps.cashflow.models import CashCut, CashMovement

    with transaction.atomic():
        # El saldo se calcula DENTRO de la transacción: si se calculara antes,
        # un movimiento registrado en el intervalo quedaría archivado en este
        # corte sin haber entrado en el saldo que el corte congela.
        box = compute_cash_box()
        cash_balance = box['cash_balance']
        transfer_balance = box['transfer_balance']

        cut = CashCut.objects.create(
            closed_by=user,
            cash_balance=cash_balance,
            transfer_balance=transfer_balance,
            withdrew_cash=withdraw_cash,
            withdrew_transfer=withdraw_transfer,
            opening_cash=Decimal('0') if withdraw_cash else cash_balance,
            opening_transfer=Decimal('0') if withdraw_transfer else transfer_balance,
            notes=(notes or '').strip(),
        )
        # Los movimientos manuales del período quedan atados al corte, igual
        # que las ventas al cierre diario: así el histórico es reconstruible.
        CashMovement.objects.filter(cash_cut__isnull=True).update(cash_cut=cut)

    return cut


def preview_cash_cut_revert(cut):
    """Qué pasaría si se deshace `cut`. No escribe nada.

    El saldo resultante NO se estima con una fórmula: se re-deriva con el mismo
    `compute_cash_box()` excluyendo el corte, que es exactamente lo que va a
    leer la pantalla después del borrado. Una identidad basada en el saldo
    congelado del corte mentiría en cuanto alguien editara una venta o un
    egreso de ese período — solo los `CashMovement` quedan atados al corte por
    FK; las ventas, egresos y pagos se filtran por fecha y siguen vivos.

    Devuelve los DOS escenarios, porque el resultado depende de una decisión
    del usuario:
      - `_if_money_left`  → el retiro que registró el corte fue real y se
                            materializa: el saldo no recupera esa plata.
      - `_if_money_stayed`→ el retiro se marcó por error: la plata vuelve.
    Sin ambos, el modal prometería el número de un escenario y ejecutaría el
    otro (el default es `money_left_the_box=True`).
    """
    latest = current_cash_cut()
    box = compute_cash_box()
    # Estado real tras borrar el corte, calculado por el mismo camino que usará
    # la pantalla. Este es el escenario "la plata se queda".
    box_after = compute_cash_box(exclude_cut_id=cut.id)

    blockers = []
    if cut.is_starting_point:
        blockers.append(
            'Este es el punto de partida de la caja y no se puede deshacer: el saldo '
            'volvería al histórico incompleto que ese corte vino a cerrar. Si el número '
            'quedó mal, corrígelo con "Ajustar saldo".'
        )
    if not latest or latest.pk != cut.pk:
        blockers.append(
            'Solo se puede deshacer el último corte. Si hay cortes posteriores, sus '
            'movimientos volverían al período en curso y aparecerían como plata de hoy.'
        )

    # Lo retirado se descuenta en el escenario "sí salió", porque ahí se
    # materializa como un CashMovement de retiro.
    retirado_cash = _to_decimal(cut.cash_balance) if cut.withdrew_cash else Decimal('0')
    retirado_transfer = _to_decimal(cut.transfer_balance) if cut.withdrew_transfer else Decimal('0')

    # ¿El período archivado sigue cuadrando con la foto que el corte congeló?
    # Solo los CashMovement quedan atados al corte por FK; las ventas, egresos
    # y pagos se filtran por fecha y siguen siendo editables. Si alguien corrigió
    # un egreso de ese período después del cierre, deshacer no devuelve el saldo
    # que el corte dice. No se oculta: se avisa.
    warnings = []
    for etiqueta, esperado, real, ahora, apertura in (
        ('efectivo', cut.cash_balance, box_after['cash_balance'], box['cash_balance'], cut.opening_cash),
        ('transferencia', cut.transfer_balance, box_after['transfer_balance'], box['transfer_balance'], cut.opening_transfer),
    ):
        desvio = _to_decimal(real) - (_to_decimal(esperado) + _to_decimal(ahora) - _to_decimal(apertura))
        if desvio != 0:
            warnings.append(
                f'El {etiqueta} de ese período ya no cuadra con lo que el corte congeló '
                f'(diferencia de ${abs(desvio):,.0f}): alguien editó o borró ventas o egresos '
                f'después de cerrarlo. El saldo que queda es el que se muestra abajo.'
            )

    return {
        'cut_id': cut.id,
        'is_latest': bool(latest and latest.pk == cut.pk),
        'is_starting_point': cut.is_starting_point,
        'blockers': blockers,
        'warnings': warnings,
        'can_revert': not blockers,
        'movements_to_release': cut.movements.count(),
        'withdrew_cash': cut.withdrew_cash,
        'withdrew_transfer': cut.withdrew_transfer,
        'withdrawn_total': retirado_cash + retirado_transfer,
        'cash_now': _to_decimal(box['cash_balance']),
        'transfer_now': _to_decimal(box['transfer_balance']),
        # Escenario "el retiro fue un error": la plata vuelve al saldo.
        'cash_after_if_money_stayed': _to_decimal(box_after['cash_balance']),
        'transfer_after_if_money_stayed': _to_decimal(box_after['transfer_balance']),
        # Escenario "la plata sí salió" (el default): se materializa el retiro.
        'cash_after_if_money_left': _to_decimal(box_after['cash_balance']) - retirado_cash,
        'transfer_after_if_money_left': _to_decimal(box_after['transfer_balance']) - retirado_transfer,
    }


def revert_cash_cut(*, cut_id, user, money_left_the_box=True):
    """Deshace un corte de caja. Devuelve (resumen, error).

    `money_left_the_box` decide qué pasa con un corte que registró retiro:
      - True  → la plata sí salió físicamente. Se materializa como un retiro
                real (`CashMovement`) para que el saldo no la resucite.
      - False → el retiro se marcó por error. La plata vuelve al saldo.

    Sin esa distinción, deshacer un corte con retiro haría aparecer plata que
    ya no está en la caja.
    """
    from apps.cashflow.models import CashCut, CashMovement

    with transaction.atomic():
        # El lock y la revalidación van DENTRO de la transacción: entre que el
        # usuario abrió la pantalla y confirmó, otro socio pudo cerrar un corte
        # nuevo, y entonces este ya no sería el último.
        cut = CashCut.objects.select_for_update().filter(pk=cut_id).first()
        if not cut:
            return None, 'Ese corte ya no existe. Recarga la pantalla.'

        preview = preview_cash_cut_revert(cut)
        if preview['blockers']:
            return None, ' '.join(preview['blockers'])

        resumen = {
            'cut_id': cut.id,
            'closed_at': timezone.localtime(cut.closed_at).strftime('%d/%m/%Y %I:%M %p'),
            'cash_balance': _to_decimal(cut.cash_balance),
            'transfer_balance': _to_decimal(cut.transfer_balance),
            'withdrew_cash': cut.withdrew_cash,
            'withdrew_transfer': cut.withdrew_transfer,
            'movements_released': cut.movements.count(),
            'materialized': [],
        }

        # El retiro que registró el corte no tiene movimiento propio: solo se
        # representa poniendo opening_* en 0. Si la plata sí salió, hay que
        # materializarlo ahora o el saldo la da por presente.
        if money_left_the_box:
            for box, retirado, monto in (
                ('cash', cut.withdrew_cash, cut.cash_balance),
                ('transfer', cut.withdrew_transfer, cut.transfer_balance),
            ):
                if retirado and _to_decimal(monto) > 0:
                    CashMovement.objects.create(
                        kind=CashMovement.KIND_WITHDRAWAL,
                        source=box,
                        amount=_to_decimal(monto),
                        description=f'Retiro del corte del {resumen["closed_at"]} (corte deshecho)',
                        created_by=user,
                    )
                    resumen['materialized'].append({'source': box, 'amount': float(_to_decimal(monto))})

        # Se desarchivan explícitamente y no por el SET_NULL implícito: así se
        # pueden contar para la auditoría y el código no depende del on_delete.
        cut.movements.update(cash_cut=None)
        cerrado_en = cut.closed_at
        cut.delete()

        # El select_for_update bloquea la fila de ESTE corte, pero no impide que
        # otro socio INSERTE un corte nuevo en paralelo (un INSERT es un
        # fantasma, no hay fila que bloquear). Bajo READ COMMITTED esta relectura
        # posterior sí ve un corte ya commiteado, así que se revalida acá y se
        # revierte todo si dejó de ser el último.
        if CashCut.objects.filter(closed_at__gt=cerrado_en).exists():
            transaction.set_rollback(True)
            return None, (
                'Otro usuario cerró un corte nuevo mientras confirmabas. '
                'No se deshizo nada: recarga la pantalla e inténtalo otra vez.'
            )

    box = compute_cash_box()
    resumen['cash_balance_now'] = _to_decimal(box['cash_balance'])
    resumen['transfer_balance_now'] = _to_decimal(box['transfer_balance'])
    return resumen, None


def set_cash_starting_point(*, user, cash, transfer, notes=''):
    """Fija el punto de partida de la caja con lo que los socios contaron.

    Necesario la primera vez: sin ningún corte previo el saldo se calcula
    sobre TODO el histórico, que arrastra el problema viejo (las inyecciones
    de capital nunca se registraron, así que el efectivo daba negativo).

    Cierra el histórico en un corte que arranca en $0 y registra el conteo
    real como ajustes, para que quede el rastro de quién declaró qué.
    """
    from apps.cashflow.models import CashMovement

    cash = _to_decimal(cash)
    transfer = _to_decimal(transfer)
    if cash < 0 or transfer < 0:
        return None, 'Los saldos contados no pueden ser negativos.'

    with transaction.atomic():
        cut = close_cash_cut(
            user=user, withdraw_cash=True, withdraw_transfer=True,
            notes=(notes or '').strip() or 'Punto de partida: se cierra el histórico previo.',
        )
        # Se marca para que no se pueda deshacer: revertirlo devolvería el
        # saldo al histórico incompleto que este corte vino justamente a cerrar.
        cut.is_starting_point = True
        cut.save(update_fields=['is_starting_point'])
        for box, amount in (('cash', cash), ('transfer', transfer)):
            if amount:
                CashMovement.objects.create(
                    kind=CashMovement.KIND_ADJUSTMENT, source=box, amount=amount,
                    description='Saldo inicial contado', created_by=user,
                )
    return cut, None


def process_checkout(*, booking, confirmed_by, payment_method_id=None,
                     payment_reference='', tip_amount=0,
                     discount_amount=0, discount_assumed_by='none',
                     added_value_amount=0, added_value_description='',
                     commission_percentage=50, notes='', 
                     frank_materials_cost=0, frank_labor_cost=0,
                     request=None):
    """
    Procesa el checkout completo de una reserva de forma atómica.
    """
    from decimal import Decimal
    from apps.cashflow.models import Expense

    if booking.status in ('completed', 'cancelled'):
        raise ValueError(
            f'La reserva #{booking.id} ya está en estado "{booking.status}" '
            'y no puede procesarse de nuevo.'
        )

    with transaction.atomic():
        # ── 1. Método de pago ───────────────────────────────────────────
        payment_method = None
        if payment_method_id:
            payment_method = PaymentMethod.objects.filter(id=payment_method_id).first()

        # ── 2. Crear Venta ──────────────────────────────────────────────
        user_profile = getattr(confirmed_by, 'profile', None)
        if user_profile and user_profile.role in ('operational_admin', 'superadmin', 'admin'):
            approval_status = Sale.STATUS_APPROVED
        else:
            approval_status = Sale.STATUS_PENDING

        # Si viene con costos de materiales (Ej. servicio manual de Frank)
        base_price = booking.price
        if frank_materials_cost > 0 or frank_labor_cost > 0:
            base_price = Decimal(str(frank_materials_cost)) + Decimal(str(frank_labor_cost))

        sale = Sale.objects.create(
            booking=booking,
            barber=booking.barber,
            service=booking.service,
            base_price=base_price,
            added_value_amount=added_value_amount,
            added_value_description=added_value_description,
            discount_amount=discount_amount,
            discount_assumed_by=discount_assumed_by,
            tip_amount=tip_amount,
            payment_method=payment_method,
            payment_reference=payment_reference,
            confirmed_by=confirmed_by,
            notes=notes,
            approval_status=approval_status,
        )

        # ── 3. Comisión y Gastos Especiales ─────────────────────────────
        if booking.barber:
            comm = Commission.objects.create(
                sale=sale,
                barber=booking.barber,
                percentage=commission_percentage,
            )
            
            # Si hay materiales separados, ajustamos la comisión y creamos el gasto
            if frank_materials_cost > 0:
                labor_val = Decimal(str(frank_labor_cost)) + Decimal(str(added_value_amount))
                
                # Aplicar descuentos si los asume el barbero o es compartido
                if sale.discount_assumed_by == Sale.BARBER_ASSUMES:
                    labor_val -= sale.discount_amount
                elif sale.discount_assumed_by == 'shared':
                    labor_val -= (sale.discount_amount / Decimal('2.0'))
                    
                percentage_dec = Decimal(str(commission_percentage)) / Decimal('100.00')
                new_comm_amt = labor_val * percentage_dec
                new_total = new_comm_amt + sale.tip_amount
                
                # Actualizamos directo en la BD para saltarnos el método save()
                Commission.objects.filter(id=comm.id).update(
                    basis_amount=labor_val,
                    commission_amount=new_comm_amt,
                    total_earnings=new_total
                )
                
                # Crear Egreso para los materiales. Etiquetamos el id de la
                # venta dentro de la descripción para que reject_sale_view
                # pueda eliminar EXACTAMENTE este egreso (no el de otra venta
                # del mismo cliente).
                Expense.objects.create(
                    description=f"{MATERIALS_EXPENSE_PREFIX} {booking.client_name} (venta #{sale.id})",
                    amount=Decimal(str(frank_materials_cost)),
                    expense_type='variable',
                    registered_by=confirmed_by
                )

        # ── 4. Descuento de Inventario ─────────────────────────────────
        if booking.service:
            for req in ServiceInventoryItem.objects.filter(service=booking.service):
                item = req.item
                qty_before = item.quantity
                item.quantity -= req.quantity_per_service
                # Nunca dejar en negativo — registra y alerta, pero no bloquea
                if item.quantity < 0:
                    item.quantity = 0
                item.save()

                InventoryMovement.objects.create(
                    item=item,
                    movement_type='out',
                    quantity=req.quantity_per_service,
                    quantity_before=qty_before,
                    quantity_after=item.quantity,
                    booking=booking,
                    performed_by=confirmed_by,
                    notes=f'Consumo automático por servicio "{booking.service.name}"',
                )

        # ── 5. Actualizar estado de la Reserva ─────────────────────────
        booking.status = 'completed'
        booking.completed_at = timezone.now()
        booking.price = sale.final_price
        booking.save(update_fields=['status', 'completed_at', 'price'])

        # ── 6. Registro de Auditoría ────────────────────────────────────
        log_audit(
            user=confirmed_by,
            action='payment',
            obj=sale,
            changes={
                'base_price': str(sale.base_price),
                'discount': str(sale.discount_amount),
                'discount_assumed_by': sale.discount_assumed_by,
                'final_price': str(sale.final_price),
                'tip': str(sale.tip_amount),
                'total_paid': str(sale.total_paid),
                'payment_method': payment_method.name if payment_method else 'Sin especificar',
                'payment_reference': payment_reference,
            },
            request=request,
            extra_data={
                'msg': (
                    f'Checkout de {booking.client_name} por ${sale.total_paid:,.0f} '
                    f'— Barbero: {booking.barber.display_name if booking.barber else "N/A"}'
                )
            },
        )

    return sale
