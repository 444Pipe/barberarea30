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
from .services import get_dashboard_context, generate_monthly_snapshot
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
