"""
ROI Views — Acceso exclusivo para SuperAdministradores (Camilo, Juan David).

El decorador @superadmin_required garantiza que solo usuarios con
role='superadmin' puedan acceder. Cualquier otro perfil es redirigido.
"""
import calendar
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib import messages
from django.utils import timezone

from apps.users.decorators import superadmin_required
from .services import (
    get_dashboard_context,
    generate_monthly_snapshot,
    delete_snapshots,
)
from .models import MonthlyROISnapshot, Partner, PartnerInvestment


# ─────────────────────────────────────────────────────────
# Panel principal ROI
# ─────────────────────────────────────────────────────────

@superadmin_required
def roi_dashboard_view(request):
    """
    Panel de ROI — solo accesible para superadmin (Camilo / Juan David).
    Muestra inversión inicial, ganancias del mes anterior y saldos pendientes.
    """
    profile = getattr(request.user, 'profile', None)
    ctx = get_dashboard_context()
    ctx.update({
        'user_role': profile.role if profile else 'unknown',
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'roi',
    })
    return render(request, 'admin/roi_dashboard.html', ctx)


# ─────────────────────────────────────────────────────────
# Generar / Consolidar Snapshot mensual (acción manual)
# ─────────────────────────────────────────────────────────

@superadmin_required
def roi_generate_snapshot_view(request):
    """
    POST: Genera o regenera el snapshot ROI del mes especificado.
    Solo superadmin puede ejecutar esta acción.
    """
    if request.method != 'POST':
        return redirect('roi_dashboard')

    try:
        year = int(request.POST.get('year', timezone.localtime(timezone.now()).year))
        month = int(request.POST.get('month', timezone.localtime(timezone.now()).month))

        if not (1 <= month <= 12):
            raise ValueError('Mes inválido.')
        if year < 2020 or year > 2100:
            raise ValueError('Año inválido.')

        snapshot = generate_monthly_snapshot(year, month, user=request.user)
        month_name = calendar.month_name[month]
        messages.success(
            request,
            f'✅ Snapshot de {month_name} {year} generado correctamente. '
            f'Ganancia neta: ${snapshot.net_income:,.0f} COP'
        )
    except ValueError as e:
        messages.error(request, f'⚠️ {e}')
    except Exception as e:
        messages.error(request, f'❌ Error inesperado: {e}')

    return redirect('roi_dashboard')


# ─────────────────────────────────────────────────────────
# Bloquear Snapshot (inmutable)
# ─────────────────────────────────────────────────────────

@superadmin_required
def roi_lock_snapshot_view(request, snapshot_id):
    """POST: Bloquea un snapshot para que no pueda modificarse."""
    if request.method != 'POST':
        return redirect('roi_dashboard')

    try:
        snapshot = MonthlyROISnapshot.objects.get(pk=snapshot_id)
        if snapshot.is_locked:
            messages.warning(request, 'Este snapshot ya estaba bloqueado.')
        else:
            snapshot.is_locked = True
            snapshot.save(update_fields=['is_locked'])
            messages.success(
                request,
                f'🔒 Snapshot de {calendar.month_name[snapshot.month]} {snapshot.year} bloqueado.'
            )
    except MonthlyROISnapshot.DoesNotExist:
        messages.error(request, 'Snapshot no encontrado.')

    return redirect('roi_dashboard')


# ─────────────────────────────────────────────────────────
# API — Datos JSON del snapshot (para gráficas futuras)
# ─────────────────────────────────────────────────────────

@superadmin_required
def roi_api_history(request):
    """
    Retorna los últimos 12 snapshots en JSON para gráficas Chart.js.
    """
    snapshots = MonthlyROISnapshot.objects.order_by('-year', '-month')[:12]
    data = []
    for s in reversed(list(snapshots)):
        data.append({
            'label': f'{calendar.month_abbr[s.month]} {s.year}',
            'net_income': float(s.net_income),
            'gross_income': float(s.gross_income),
            'expenses': float(s.total_expenses),
            'commissions': float(s.total_commissions),
        })
    return JsonResponse({'history': data})


# ─────────────────────────────────────────────────────────
# Registrar Inversión (Aporte de Capital)
# ─────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────
# Limpiar snapshots (Fase 3 — reset selectivo de periodos corruptos)
# ─────────────────────────────────────────────────────────

@superadmin_required
def roi_clean_snapshots_view(request):
    """
    POST: Borra snapshots de periodos específicos enviados como 'periods'
    en formato 'M/YYYY' separados por coma o espacio. Por defecto NO toca
    snapshots bloqueados a menos que se envíe force_locked=1.
    """
    if request.method != 'POST':
        return redirect('roi_dashboard')

    raw_periods = (request.POST.get('periods') or '').replace(',', ' ').split()
    force_locked = request.POST.get('force_locked') == '1'

    if not raw_periods:
        messages.error(request, '⚠️ Debes indicar al menos un periodo (ej: 2/2026 3/2026 4/2026).')
        return redirect('roi_dashboard')

    periods = []
    for raw in raw_periods:
        try:
            if '/' in raw:
                m, y = raw.split('/')
            elif '-' in raw:
                y, m = raw.split('-')
            else:
                raise ValueError(f'formato inválido en "{raw}"')
            year = int(y)
            month = int(m)
            if not (1 <= month <= 12) or not (2020 <= year <= 2100):
                raise ValueError(f'rango fuera de límites en "{raw}"')
            periods.append((year, month))
        except ValueError as e:
            messages.error(request, f'⚠️ Periodo inválido: {raw}. Usa formato M/YYYY (ej: 4/2026).')
            return redirect('roi_dashboard')

    try:
        result = delete_snapshots(periods, force_locked=force_locked)
        msg = f'🧹 Eliminados {result["deleted"]} snapshots.'
        if result['skipped_locked']:
            locked_str = ', '.join(f'{m}/{y}' for (y, m) in result['skipped_locked'])
            msg += f' Saltados (bloqueados): {locked_str}.'
        messages.success(request, msg)
    except Exception as e:
        messages.error(request, f'❌ Error limpiando snapshots: {e}')

    return redirect('roi_dashboard')


@superadmin_required
def roi_add_investment_view(request):
    """POST: Registra un nuevo aporte de capital para un socio."""
    if request.method != 'POST':
        return redirect('roi_dashboard')

    try:
        partner_id = request.POST.get('partner_id')
        amount = request.POST.get('amount')
        description = request.POST.get('description', 'Aporte de capital')

        if not partner_id or not amount:
            raise ValueError('Socio y monto son obligatorios.')

        partner = Partner.objects.get(pk=partner_id)
        
        PartnerInvestment.objects.create(
            partner=partner,
            amount=amount,
            description=description,
            registered_by=request.user
        )
        
        messages.success(request, f'✅ Inversión de ${int(float(amount)):,.0f} registrada para {partner.display_name}.')
    except Exception as e:
        messages.error(request, f'❌ Error al registrar inversión: {e}')

    return redirect('roi_dashboard')
