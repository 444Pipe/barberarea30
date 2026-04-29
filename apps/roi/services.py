"""
ROI Services — Lógica de negocio para calcular y consolidar el ROI mensual.

Funciones principales:
  - get_net_income_for_month(year, month)  → Decimal
  - generate_monthly_snapshot(year, month, user) → MonthlyROISnapshot
  - get_or_compute_latest_snapshot()       → dict con datos para la vista
"""
import calendar
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.contrib.auth.models import User

from apps.cashflow.models import Sale, Commission, Expense
from .models import Partner, PartnerInvestment, MonthlyROISnapshot, PartnerMonthlyShare


def _month_date_range(year: int, month: int):
    """Retorna (fecha_inicio, fecha_fin) para el mes dado."""
    from datetime import date
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def get_net_income_for_month(year: int, month: int) -> dict:
    """
    Calcula ingresos brutos, comisiones y egresos para un mes específico.
    Retorna un dict con gross_income, total_commissions, total_expenses, net_income.
    """
    start, end = _month_date_range(year, month)

    # Solo ventas aprobadas del mes
    sales_qs = Sale.objects.filter(
        created_at__date__gte=start,
        created_at__date__lte=end,
        approval_status='approved',
    )

    gross = sales_qs.aggregate(t=Sum('final_price'))['t'] or Decimal('0')

    commissions = Commission.objects.filter(
        sale__in=sales_qs
    ).aggregate(t=Sum('commission_amount'))['t'] or Decimal('0')

    expenses = Expense.objects.filter(
        date__gte=start,
        date__lte=end,
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    net = gross - commissions - expenses

    return {
        'gross_income': Decimal(gross),
        'total_commissions': Decimal(commissions),
        'total_expenses': Decimal(expenses),
        'net_income': Decimal(net),
    }


def _get_partner_investment_balance(partner: Partner, up_to_snapshot_id=None) -> Decimal:
    """
    Calcula el saldo pendiente de inversión del socio ANTES del snapshot indicado.
    Si up_to_snapshot_id es None, devuelve el saldo actual (considerando todos los snapshots).
    """
    # Inversión total del socio
    total_invested = partner.investments.aggregate(
        t=Sum('amount')
    )['t'] or Decimal('0')

    # Suma de amortizaciones ya aplicadas en snapshots anteriores
    share_qs = PartnerMonthlyShare.objects.filter(partner=partner)
    if up_to_snapshot_id is not None:
        share_qs = share_qs.filter(snapshot_id__lt=up_to_snapshot_id)

    already_amortized = share_qs.aggregate(
        t=Sum('amortization_applied')
    )['t'] or Decimal('0')

    balance = total_invested - already_amortized
    return max(balance, Decimal('0'))


@transaction.atomic
def generate_monthly_snapshot(year: int, month: int, user: User = None) -> MonthlyROISnapshot:
    """
    Genera (o regenera si no está bloqueado) el snapshot ROI para el mes indicado.
    Calcula la distribución para cada socio activo y sus amortizaciones.
    """
    # Verificar si ya existe y está bloqueado
    existing = MonthlyROISnapshot.objects.filter(year=year, month=month).first()
    if existing and existing.is_locked:
        raise ValueError(
            f'El snapshot de {calendar.month_name[month]} {year} ya está bloqueado. '
            'No puede regenerarse.'
        )

    # Datos financieros del mes
    financials = get_net_income_for_month(year, month)

    # Crear o actualizar snapshot
    snapshot, _ = MonthlyROISnapshot.objects.update_or_create(
        year=year,
        month=month,
        defaults={
            'gross_income': financials['gross_income'],
            'total_commissions': financials['total_commissions'],
            'total_expenses': financials['total_expenses'],
            'net_income': financials['net_income'],
            'created_by': user,
        }
    )

    # Limpiar shares anteriores (si se está regenerando)
    snapshot.partner_shares.all().delete()

    # Distribución para cada socio activo
    partners = Partner.objects.filter(is_active=True)
    for partner in partners:
        share_pct = partner.share_percentage
        gross_share = (financials['net_income'] * share_pct / Decimal('100')).quantize(Decimal('1'))

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


def get_dashboard_context() -> dict:
    """
    Retorna todos los datos necesarios para renderizar el panel ROI.
    Si no existe snapshot del mes anterior, lo calcula dinámicamente (sin guardar).
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
        invested = partner.investments.aggregate(t=Sum('amount'))['t'] or Decimal('0')
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

    # ── Snapshot del mes anterior ──
    last_snapshot = MonthlyROISnapshot.objects.filter(
        year=prev_year, month=prev_month
    ).prefetch_related('partner_shares__partner').first()

    # Si no existe snapshot guardado, calcular dinámicamente (read-only)
    prev_financials = get_net_income_for_month(prev_year, prev_month)

    # ── Historial de snapshots (últimos 12) ──
    history = MonthlyROISnapshot.objects.prefetch_related(
        'partner_shares__partner'
    ).order_by('-year', '-month')[:12]

    return {
        # Inversión
        'partners': partner_data,
        'total_invested': total_invested,
        'total_recovered': total_recovered,
        'total_pending': current_total_pending,

        # Mes anterior (datos financieros)
        'prev_year': prev_year,
        'prev_month': prev_month,
        'prev_month_name': calendar.month_name[prev_month],
        'prev_gross': prev_financials['gross_income'],
        'prev_commissions': prev_financials['total_commissions'],
        'prev_expenses': prev_financials['total_expenses'],
        'prev_net': prev_financials['net_income'],

        # Snapshot guardado (si existe)
        'last_snapshot': last_snapshot,

        # Mes actual
        'current_year': now.year,
        'current_month': now.month,
        'current_month_name': calendar.month_name[now.month],

        # Historial
        'history': history,
    }
