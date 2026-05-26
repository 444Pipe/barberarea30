"""Context processors disponibles globalmente en todos los templates."""


def admin_badges(request):
    """Inyecta contadores que el sidebar del admin usa como badges.

    Calcula los valores solo si hay un usuario autenticado con rol
    operacional o superior; en cualquier otro caso devuelve un dict
    con 0 para evitar cualquier consulta a la BD.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {'pending_approvals_count': 0}

    profile = getattr(user, 'profile', None)
    if not profile or profile.role not in ('admin', 'operational_admin', 'superadmin'):
        return {'pending_approvals_count': 0}

    try:
        from apps.cashflow.models import Sale
        count = Sale.objects.filter(
            approval_status=Sale.STATUS_PENDING,
            included_in_daily_close__isnull=True,
        ).count()
    except Exception:
        count = 0

    return {'pending_approvals_count': count}
