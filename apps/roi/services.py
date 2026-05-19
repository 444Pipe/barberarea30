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

def get_month_financials(year: int, month: int) -> dict:
    """
    Cierre financiero estricto para el mes (year, month). NO persiste.

    Devuelve un dict con todas las cifras necesarias para crear (o regenerar)
    el MonthlyROISnapshot. Se usa también en la vista en tiempo real para
    mostrar el mes anterior aún sin consolidar.
    """
    start, end = _month_date_range(year, month)

    # ── 1. Ingresos por servicios (solo ventas aprobadas) ──
    services_qs = Sale.objects.filter(
        created_at__date__gte=start,
        created_at__date__lte=end,
        approval_status=Sale.STATUS_APPROVED,
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

def get_dashboard_context() -> dict:
    """
    Retorna todos los datos necesarios para renderizar el panel ROI.
    Si no existe snapshot del mes anterior, calcula las cifras al vuelo (sin guardar).
    """
    from django.utils import timezone
    now = timezone.localtime(timezone.now())

    # Mes anterior
    if now.month == 1:
        prev_year, prev_month = now.year - 1, 12
    else:
        prev_year, prev_month = now.year, now.month - 1

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

    # ── Mes anterior: usar snapshot si está consolidado, sino calcular en vivo ──
    last_snapshot = MonthlyROISnapshot.objects.filter(
        year=prev_year, month=prev_month
    ).prefetch_related('partner_shares__partner').first()

    if last_snapshot:
        prev = {
            'gross_services': last_snapshot.gross_services,
            'total_inventory_sales': last_snapshot.total_inventory_sales,
            'gross_income': last_snapshot.gross_income,
            'total_commissions': last_snapshot.total_commissions,
            'total_fixed_expenses': last_snapshot.total_fixed_expenses,
            'total_operational_expenses': last_snapshot.total_operational_expenses,
            'total_expenses': last_snapshot.total_expenses,
            'net_income': last_snapshot.net_income,
        }
    else:
        prev = get_month_financials(prev_year, prev_month)

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

        # Mes anterior — desglose completo
        'prev_year': prev_year,
        'prev_month': prev_month,
        'prev_month_name': calendar.month_name[prev_month],
        'prev_gross_services': prev['gross_services'],
        'prev_inventory': prev['total_inventory_sales'],
        'prev_gross': prev['gross_income'],
        'prev_commissions': prev['total_commissions'],
        'prev_fixed_expenses': prev['total_fixed_expenses'],
        'prev_operational_expenses': prev['total_operational_expenses'],
        'prev_expenses': prev['total_expenses'],
        'prev_net': prev['net_income'],

        # Snapshot consolidado (si existe)
        'last_snapshot': last_snapshot,

        # Mes actual
        'current_year': now.year,
        'current_month': now.month,
        'current_month_name': calendar.month_name[now.month],

        # Historial
        'history': history,
    }
