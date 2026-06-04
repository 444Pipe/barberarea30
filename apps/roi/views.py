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
    get_investment_summary,
)
from .models import MonthlyROISnapshot, Partner, PartnerInvestment


# ─────────────────────────────────────────────────────────
# Panel principal ROI
# ─────────────────────────────────────────────────────────

@superadmin_required
def roi_dashboard_view(request):
    """
    Panel de ROI — solo accesible para superadmin (Camilo / Juan David).
    Muestra inversión inicial, ganancias del mes seleccionado y saldos pendientes.

    Acepta ?year=YYYY&month=M para navegar entre meses. Por defecto muestra el
    mes en curso, calculado en vivo si aún no hay snapshot consolidado.
    """
    profile = getattr(request.user, 'profile', None)

    sel_year = request.GET.get('year')
    sel_month = request.GET.get('month')
    try:
        sel_year = int(sel_year) if sel_year else None
        sel_month = int(sel_month) if sel_month else None
        if sel_month is not None and not (1 <= sel_month <= 12):
            sel_year, sel_month = None, None
    except (TypeError, ValueError):
        sel_year, sel_month = None, None

    ctx = get_dashboard_context(selected_year=sel_year, selected_month=sel_month)
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


# ─────────────────────────────────────────────────────────
# Historial de Aportes — CRUD (listar / editar / eliminar)
# ─────────────────────────────────────────────────────────

def _investment_summary_payload():
    """Totales recalculados (globales + por socio) para refrescar los KPI en vivo."""
    summary = get_investment_summary()
    return {
        'total_invested': int(summary['total_invested']),
        'total_recovered': int(summary['total_recovered']),
        'total_pending': int(summary['total_pending']),
        'partners': [
            {
                'id': pd['partner'].id,
                'name': pd['partner'].display_name,
                'total_invested': int(pd['total_invested']),
                'total_recovered': int(pd['total_recovered']),
                'pending_balance': int(pd['pending_balance']),
                'recovery_pct': pd['recovery_pct'],
            }
            for pd in summary['partners']
        ],
    }


@superadmin_required
def roi_api_investments(request):
    """GET: Lista todos los aportes individuales para el modal de historial."""
    investments = (
        PartnerInvestment.objects
        .select_related('partner', 'registered_by')
        .order_by('-date', '-id')
    )
    items = [
        {
            'id': inv.id,
            'partner_id': inv.partner_id,
            'partner_name': inv.partner.display_name,
            'amount': int(inv.amount),
            'description': inv.description or '',
            'date': inv.date.isoformat(),
            'registered_by': (
                inv.registered_by.get_full_name() or inv.registered_by.username
            ) if inv.registered_by else '—',
        }
        for inv in investments
    ]
    return JsonResponse({'investments': items, 'summary': _investment_summary_payload()})


@superadmin_required
def roi_update_investment_view(request, investment_id):
    """
    POST: Edita un aporte (socio, monto, concepto, fecha).

    Como los totales son derivados (se agregan desde PartnerInvestment), basta
    con guardar la fila: el "Saldo Pendiente", la "Inversión Total" global y el
    total por socio se recalculan solos. Devolvemos el resumen ya recalculado
    para que el front actualice los KPI sin recargar.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido.'}, status=405)

    try:
        inv = PartnerInvestment.objects.get(pk=investment_id)
    except PartnerInvestment.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Aporte no encontrado.'}, status=404)

    try:
        partner_id = request.POST.get('partner_id')
        amount = request.POST.get('amount')
        description = request.POST.get('description', '').strip()
        date_str = request.POST.get('date')

        if not partner_id or not amount:
            raise ValueError('Socio y monto son obligatorios.')

        amount_val = int(float(amount))
        if amount_val <= 0:
            raise ValueError('El monto debe ser mayor a 0.')

        inv.partner = Partner.objects.get(pk=partner_id)
        inv.amount = amount_val
        inv.description = description
        if date_str:
            inv.date = date_str  # 'YYYY-MM-DD' → Django lo parsea al guardar
        inv.save()
    except Partner.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Socio no encontrado.'}, status=404)
    except (ValueError, TypeError) as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'Error inesperado: {e}'}, status=500)

    return JsonResponse({'ok': True, 'summary': _investment_summary_payload()})


@superadmin_required
def roi_delete_investment_view(request, investment_id):
    """
    POST: Elimina un aporte. El monto se descuenta automáticamente de la
    Inversión Total global, del Saldo Pendiente y del total del socio, porque
    todos esos valores se derivan al recalcular get_investment_summary().
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido.'}, status=405)

    try:
        inv = PartnerInvestment.objects.get(pk=investment_id)
    except PartnerInvestment.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Aporte no encontrado.'}, status=404)

    inv.delete()
    return JsonResponse({'ok': True, 'summary': _investment_summary_payload()})
