"""
ROI Services — Lógica de negocio para calcular y consolidar el ROI mensual.

Reglas de negocio (Área 30 Barber Club):
  • Ingresos Brutos      = Servicios aprobados del mes + Ventas de inventario del mes
  • Comisiones           = Suma de Commission.commission_amount del mes
                           (40% staff general / 50% Frank — el % vive en Barber.commission_percentage
                           y en Commission.percentage, recalculado por Commission.save()).
  • Egresos Operativos   = Expense (variable + inventory) EXCLUYENDO "Pago Diario: Franko"
                           (ese pago ya está representado en la Commission de Frank al 50% —
                           contarlo en egresos lo duplicaría).
  • Egresos Fijos        = Expense con expense_type='fixed' (arriendo, servicios, nómina).
  • Ganancia Neta        = Bruto − Comisiones − Egresos Operativos − Egresos Fijos
  • Distribución ROI     = Si Neto > 0, se reparte por share_percentage del socio y se amortiza
                           contra su saldo de inversión pendiente.
  • Bloqueo              = is_locked=True hace inmutable el snapshot (lo cuida la vista lock).
"""
import calendar
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.cashflow.models import Sale, Commission, Expense, InventorySale
from .models import (
    MonthlyROISnapshot,
    Partner,
    PartnerInvestment,
    PartnerMonthlyShare,
)


# Descripción canónica del egreso auto-generado por DailyClose cuando se paga a Frank.
# Si cambia en apps/cashflow/views.py, actualizar aquí también.
FRANK_DAILY_EXPENSE_DESC = 'Pago Diario: Franko'


# Inicio de operatividad del Club. El panel ROI no permite navegar a meses anteriores
# porque no hay datos reales que reflejar. Si en el futuro arranca una nueva sede o
# se reinicia el conteo, actualizar esta constante.
OPERATION_START = (2026, 5)


# ─────────────────────────────────────────────────────────
# Utilidades de rango
# ─────────────────────────────────────────────────────────

def _month_date_range(year: int, month: int):
    """Retorna (fecha_inicio, fecha_fin) inclusivo para el mes dado."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _D(value) -> Decimal:
    """Asegura Decimal a partir de un valor (None → 0)."""
    if value is None:
        return Decimal('0')
    return value if isinstance(value, Decimal) else Decimal(str(value))


# ─────────────────────────────────────────────────────────
# Cálculo financiero del mes
# ─────────────────────────────────────────────────────────

def get_month_financials(year: int, month: int, *, include_pending: bool = False) -> dict:
    """
    Cierre financiero para el mes (year, month). NO persiste.

    Por defecto sólo cuenta ventas con `approval_status='approved'` — este es el
    criterio que usa la consolidación (snapshot definitivo).

    Si `include_pending=True`, también suma las ventas en estado 'pending'. Esto
    se usa en la vista del mes EN CURSO para reflejar la operatividad real del
    negocio en tiempo real, sin esperar a que cada venta sea aprobada.
    """
    start, end = _month_date_range(year, month)

    # ── 1. Ingresos por servicios ──
    valid_statuses = [Sale.STATUS_APPROVED]
    if include_pending:
        valid_statuses.append(Sale.STATUS_PENDING)

    services_qs = Sale.objects.filter(
        created_at__date__gte=start,
        created_at__date__lte=end,
        approval_status__in=valid_statuses,
    )
    gross_services = _D(services_qs.aggregate(t=Sum('final_price'))['t'])

    # ── 2. Ingresos por venta de inventario ──
    inventory_qs = InventorySale.objects.filter(
        created_at__date__gte=start,
        created_at__date__lte=end,
    )
    total_inventory_sales = _D(inventory_qs.aggregate(t=Sum('total_price'))['t'])

    gross_income = gross_services + total_inventory_sales

    # ── 3. Comisiones (40% general / 50% Frank, ya viene aplicado en cada Commission) ──
    total_commissions = _D(
        Commission.objects.filter(sale__in=services_qs)
        .aggregate(t=Sum('commission_amount'))['t']
    )

    # ── 4. Egresos del mes (separación fijos / operativos) ──
    expense_qs = Expense.objects.filter(date__gte=start, date__lte=end)

    total_fixed_expenses = _D(
        expense_qs.filter(expense_type='fixed').aggregate(t=Sum('amount'))['t']
    )

    # Operativos = variables + compras de inventario, EXCLUYENDO "Pago Diario: Franko"
    # (ese pago ya está representado en Commission al 50% → contarlo aquí lo duplicaría).
    operational_qs = (
        expense_qs.filter(expense_type__in=['variable', 'inventory'])
        .exclude(description__iexact=FRANK_DAILY_EXPENSE_DESC)
    )
    total_operational_expenses = _D(operational_qs.aggregate(t=Sum('amount'))['t'])

    total_expenses = total_fixed_expenses + total_operational_expenses

    # ── 5. Neto ──
    net_income = gross_income - total_commissions - total_expenses

    return {
        'gross_services': gross_services,
        'total_inventory_sales': total_inventory_sales,
        'gross_income': gross_income,
        'total_commissions': total_commissions,
        'total_fixed_expenses': total_fixed_expenses,
        'total_operational_expenses': total_operational_expenses,
        'total_expenses': total_expenses,
        'net_income': net_income,
    }


def get_month_diagnostics(year: int, month: int) -> dict:
    """
    Devuelve un breakdown crudo de TODOS los registros del mes (sin filtros de
    aprobación) para que el panel ROI muestre qué hay realmente en la base de
    datos. Sirve para detectar de un vistazo si las cifras no aparecen porque
    las ventas están en estado 'pending' o 'rejected' en vez de 'approved'.
    """
    start, end = _month_date_range(year, month)

    sales_qs = Sale.objects.filter(
        created_at__date__gte=start, created_at__date__lte=end
    )

    by_status = {}
    for status_value, _label in Sale.APPROVAL_STATUS_CHOICES:
        sub = sales_qs.filter(approval_status=status_value)
        by_status[status_value] = {
            'count': sub.count(),
            'total': _D(sub.aggregate(t=Sum('final_price'))['t']),
        }

    inventory_qs = InventorySale.objects.filter(
        created_at__date__gte=start, created_at__date__lte=end
    )
    expense_qs = Expense.objects.filter(date__gte=start, date__lte=end)

    return {
        'sales_total_all': sales_qs.count(),
        'sales_approved_count': by_status[Sale.STATUS_APPROVED]['count'],
        'sales_approved_total': by_status[Sale.STATUS_APPROVED]['total'],
        'sales_pending_count': by_status[Sale.STATUS_PENDING]['count'],
        'sales_pending_total': by_status[Sale.STATUS_PENDING]['total'],
        'sales_rejected_count': by_status[Sale.STATUS_REJECTED]['count'],
        'sales_rejected_total': by_status[Sale.STATUS_REJECTED]['total'],
        'inventory_count': inventory_qs.count(),
        'inventory_total': _D(inventory_qs.aggregate(t=Sum('total_price'))['t']),
        'expenses_count': expense_qs.count(),
        'expenses_total': _D(expense_qs.aggregate(t=Sum('amount'))['t']),
    }


# Alias hacia atrás-compatible (vistas antiguas pueden seguir importando esto)
def get_net_income_for_month(year: int, month: int) -> dict:
    return get_month_financials(year, month)


# ─────────────────────────────────────────────────────────
# Saldo de inversión por socio
# ─────────────────────────────────────────────────────────

def _get_partner_investment_balance(partner: Partner, up_to_snapshot_id=None) -> Decimal:
    """
    Saldo pendiente del socio antes del snapshot indicado.
    Si up_to_snapshot_id es None, considera todas las amortizaciones registradas.
    """
    total_invested = _D(partner.investments.aggregate(t=Sum('amount'))['t'])

    share_qs = PartnerMonthlyShare.objects.filter(partner=partner)
    if up_to_snapshot_id is not None:
        share_qs = share_qs.filter(snapshot_id__lt=up_to_snapshot_id)

    already_amortized = _D(share_qs.aggregate(t=Sum('amortization_applied'))['t'])
    balance = total_invested - already_amortized
    return max(balance, Decimal('0'))


# ─────────────────────────────────────────────────────────
# Consolidación del Mes (botón "Consolidar Mes")
# ─────────────────────────────────────────────────────────

@transaction.atomic
def generate_monthly_snapshot(year: int, month: int, user: User = None) -> MonthlyROISnapshot:
    """
    Genera (o regenera, si no está bloqueado) el snapshot ROI del mes (year, month).

    Flujo:
      1. Si el snapshot ya está is_locked=True, levanta ValueError (no se altera).
      2. Calcula bruto/comisiones/egresos/neto vía get_month_financials.
      3. Persiste MonthlyROISnapshot con desglose completo.
      4. Para cada socio activo: calcula share, amortiza contra su saldo
         pendiente y guarda PartnerMonthlyShare (reemplaza los previos).
      5. NO bloquea el snapshot — el bloqueo es una acción aparte (roi_lock).
    """
    existing = MonthlyROISnapshot.objects.filter(year=year, month=month).first()
    if existing and existing.is_locked:
        raise ValueError(
            f'El snapshot de {calendar.month_name[month]} {year} ya está bloqueado. '
            'No puede regenerarse.'
        )

    f = get_month_financials(year, month)

    snapshot, _ = MonthlyROISnapshot.objects.update_or_create(
        year=year,
        month=month,
        defaults={
            'gross_services': f['gross_services'],
            'total_inventory_sales': f['total_inventory_sales'],
            'gross_income': f['gross_income'],
            'total_commissions': f['total_commissions'],
            'total_fixed_expenses': f['total_fixed_expenses'],
            'total_operational_expenses': f['total_operational_expenses'],
            'total_expenses': f['total_expenses'],
            'net_income': f['net_income'],
            'created_by': user,
        },
    )

    # Reemplazar shares previas (en caso de regeneración).
    snapshot.partner_shares.all().delete()

    # Distribución ROI: solo si hay ganancia neta positiva.
    net = f['net_income']
    for partner in Partner.objects.filter(is_active=True):
        share_pct = partner.share_percentage

        if net > 0:
            gross_share = (net * share_pct / Decimal('100')).quantize(Decimal('1'))
        else:
            gross_share = Decimal('0')

        balance_before = _get_partner_investment_balance(partner, up_to_snapshot_id=snapshot.pk)
        amortization = min(gross_share, balance_before)
        balance_after = max(balance_before - amortization, Decimal('0'))
        cash_out = gross_share - amortization

        PartnerMonthlyShare.objects.create(
            snapshot=snapshot,
            partner=partner,
            share_percentage=share_pct,
            gross_share=gross_share,
            investment_balance_before=balance_before,
            amortization_applied=amortization,
            investment_balance_after=balance_after,
            cash_out=cash_out,
        )

    return snapshot


# ─────────────────────────────────────────────────────────
# Limpieza selectiva de snapshots (Fase 3 — reset 2/2026, 3/2026, 4/2026)
# ─────────────────────────────────────────────────────────

@transaction.atomic
def delete_snapshots(periods: list, *, force_locked: bool = False) -> dict:
    """
    Borra los snapshots cuyos (year, month) figuran en `periods`.
    `periods` es una lista de tuplas (year:int, month:int).

    Retorna un dict {deleted: int, skipped_locked: list[(year, month)]}.
    Por defecto NO toca snapshots con is_locked=True (a menos que force_locked=True).
    """
    deleted = 0
    skipped_locked = []

    for (y, m) in periods:
        snap = MonthlyROISnapshot.objects.filter(year=y, month=m).first()
        if not snap:
            continue
        if snap.is_locked and not force_locked:
            skipped_locked.append((y, m))
            continue
        snap.delete()  # CASCADE elimina partner_shares
        deleted += 1

    return {'deleted': deleted, 'skipped_locked': skipped_locked}


# ─────────────────────────────────────────────────────────
# Contexto del Dashboard
# ─────────────────────────────────────────────────────────

def _clamp_to_operation_window(year: int, month: int):
    """
    Restringe (year, month) al rango [OPERATION_START, mes actual]. Devuelve la
    tupla ajustada para que la vista nunca intente mostrar un mes anterior al
    arranque del negocio ni uno futuro sin datos.
    """
    from django.utils import timezone
    now = timezone.localtime(timezone.now())
    current = (now.year, now.month)
    candidate = (year, month)

    if candidate < OPERATION_START:
        return OPERATION_START
    if candidate > current:
        return current
    return candidate


def _shift_month(year: int, month: int, delta: int):
    """Suma `delta` meses a (year, month) y devuelve (y, m)."""
    idx = year * 12 + (month - 1) + delta
    return idx // 12, (idx % 12) + 1


def get_dashboard_context(selected_year: int = None, selected_month: int = None) -> dict:
    """
    Retorna todos los datos necesarios para renderizar el panel ROI.

    Si `selected_year`/`selected_month` no se pasan, usa el mes en curso. El mes
    pedido se acota al rango [OPERATION_START, mes actual]. Si existe un snapshot
    consolidado para ese mes se usan sus cifras; si no, se calculan en vivo con
    `get_month_financials`.
    """
    from django.utils import timezone
    now = timezone.localtime(timezone.now())

    if selected_year is None or selected_month is None:
        sel_year, sel_month = now.year, now.month
    else:
        sel_year, sel_month = selected_year, selected_month

    sel_year, sel_month = _clamp_to_operation_window(sel_year, sel_month)

    # Navegación: prev / next acotados al rango operativo.
    prev_y, prev_m = _shift_month(sel_year, sel_month, -1)
    next_y, next_m = _shift_month(sel_year, sel_month, +1)
    can_go_prev = (prev_y, prev_m) >= OPERATION_START
    can_go_next = (next_y, next_m) <= (now.year, now.month)
    is_current_month = (sel_year, sel_month) == (now.year, now.month)

    # ── Inversión Global ──
    partners = Partner.objects.filter(is_active=True).prefetch_related('investments')
    partner_data = []
    total_invested = Decimal('0')
    current_total_pending = Decimal('0')

    for partner in partners:
        invested = _D(partner.investments.aggregate(t=Sum('amount'))['t'])
        pending = _get_partner_investment_balance(partner)
        recovered = invested - pending
        total_invested += invested
        current_total_pending += pending

        partner_data.append({
            'partner': partner,
            'total_invested': invested,
            'total_recovered': recovered,
            'pending_balance': pending,
            'recovery_pct': int((recovered / invested * 100).quantize(Decimal('1'))) if invested > 0 else 0,
        })

    total_recovered = total_invested - current_total_pending

    # ── Mes seleccionado: usar snapshot si está consolidado, sino calcular en vivo ──
    selected_snapshot = MonthlyROISnapshot.objects.filter(
        year=sel_year, month=sel_month
    ).prefetch_related('partner_shares__partner').first()

    if selected_snapshot:
        sel = {
            'gross_services': selected_snapshot.gross_services,
            'total_inventory_sales': selected_snapshot.total_inventory_sales,
            'gross_income': selected_snapshot.gross_income,
            'total_commissions': selected_snapshot.total_commissions,
            'total_fixed_expenses': selected_snapshot.total_fixed_expenses,
            'total_operational_expenses': selected_snapshot.total_operational_expenses,
            'total_expenses': selected_snapshot.total_expenses,
            'net_income': selected_snapshot.net_income,
        }
    else:
        # Para el mes en curso incluimos también ventas 'pending' → operatividad en vivo.
        # Para meses pasados sin consolidar, solo aprobadas (criterio del ledger oficial).
        sel = get_month_financials(
            sel_year, sel_month, include_pending=is_current_month
        )

    # ── Diagnóstico crudo del mes (cuenta TODO sin filtros, para depuración) ──
    diagnostics = get_month_diagnostics(sel_year, sel_month)

    # ── Historial (últimos 12) ──
    history = MonthlyROISnapshot.objects.prefetch_related(
        'partner_shares__partner'
    ).order_by('-year', '-month')[:12]

    return {
        # Inversión
        'partners': partner_data,
        'total_invested': total_invested,
        'total_recovered': total_recovered,
        'total_pending': current_total_pending,

        # Mes seleccionado — desglose completo
        # (alias `prev_*` se mantienen por compatibilidad con el template existente)
        'sel_year': sel_year,
        'sel_month': sel_month,
        'sel_month_name': calendar.month_name[sel_month],
        'prev_year': sel_year,
        'prev_month': sel_month,
        'prev_month_name': calendar.month_name[sel_month],
        'prev_gross_services': sel['gross_services'],
        'prev_inventory': sel['total_inventory_sales'],
        'prev_gross': sel['gross_income'],
        'prev_commissions': sel['total_commissions'],
        'prev_fixed_expenses': sel['total_fixed_expenses'],
        'prev_operational_expenses': sel['total_operational_expenses'],
        'prev_expenses': sel['total_expenses'],
        'prev_net': sel['net_income'],

        # Snapshot consolidado (si existe para el mes seleccionado)
        'last_snapshot': selected_snapshot,

        # Estado del mes seleccionado respecto al calendario
        'is_current_month': is_current_month,
        'is_live_month': is_current_month and selected_snapshot is None,

        # Diagnóstico crudo del mes (lo que hay en la BD, sin filtros de aprobación)
        'diagnostics': diagnostics,

        # Navegación
        'prev_nav_year': prev_y,
        'prev_nav_month': prev_m,
        'next_nav_year': next_y,
        'next_nav_month': next_m,
        'can_go_prev': can_go_prev,
        'can_go_next': can_go_next,
        'operation_start_year': OPERATION_START[0],
        'operation_start_month': OPERATION_START[1],

        # Mes actual (calendario, no el seleccionado)
        'current_year': now.year,
        'current_month': now.month,
        'current_month_name': calendar.month_name[now.month],

        # Historial
        'history': history,
    }
