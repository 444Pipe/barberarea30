"""User authentication views and admin panel page views."""
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse

from .decorators import staff_required, admin_required, role_required


def admin_login_view(request):
    """Custom login page with Área 30 branding."""
    if request.user.is_authenticated:
        return redirect('admin_dashboard')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip().lower()
        password = request.POST.get('password', '').strip()
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            # Redirect based on role
            profile = getattr(user, 'profile', None)
            if profile and profile.is_barber and not profile.is_admin:
                return redirect('admin_barber_agenda')
            return redirect('admin_dashboard')
        else:
            error = 'Credenciales inválidas'

    return render(request, 'admin/login.html', {'error': error})


def admin_logout_view(request):
    logout(request)
    return redirect('admin_login')


@staff_required
def admin_dashboard_view(request):
    """Dashboard principal — inyecta KPIs reales del día o la fecha seleccionada."""
    from apps.bookings.models import Booking
    from apps.cashflow.models import Sale
    from django.db.models import Sum, Count
    from django.utils import timezone
    import datetime

    profile = getattr(request.user, 'profile', None)
    
    date_str = request.GET.get('date')
    if date_str:
        try:
            today = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            today = timezone.localtime(timezone.now()).date()
    else:
        today = timezone.localtime(timezone.now()).date()

    # Calculate dates for navigation
    prev_date = today - datetime.timedelta(days=1)
    next_date = today + datetime.timedelta(days=1)
    is_today = (today == timezone.localtime(timezone.now()).date())

    base = Booking.objects.all()
    if profile and profile.is_barber and not profile.is_admin:
        barber = getattr(request.user, 'barber_profile', None)
        base = base.filter(barber=barber) if barber else base.none()

    today_bookings = base.filter(date=today)
    today_completed = today_bookings.filter(status='completed').count()
    today_pending = today_bookings.filter(status__in=['pending', 'confirmed']).count()

    # Revenue today from Sales model (more accurate)
    today_sales = Sale.objects.filter(created_at__date=today)
    today_revenue = float(today_sales.aggregate(t=Sum('final_price'))['t'] or 0)
    today_tips = float(today_sales.aggregate(t=Sum('tip_amount'))['t'] or 0)

    # Top barber today
    top_today = (
        today_bookings.filter(status='completed')
        .values('barber__display_name')
        .annotate(cuts=Count('id'))
        .order_by('-cuts')
        .first()
    )

    pending_approvals_count = 0
    if profile and profile.role in ('operational_admin', 'superadmin', 'admin'):
        pending_approvals_count = Sale.objects.filter(approval_status=Sale.STATUS_PENDING, included_in_daily_close__isnull=True).count()

    context = {
        'user_role': profile.role if profile else 'unknown',
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'dashboard',
        'today': today,
        'today_str': today.strftime('%Y-%m-%d'),
        'prev_date': prev_date.strftime('%Y-%m-%d'),
        'next_date': next_date.strftime('%Y-%m-%d'),
        'is_today': is_today,
        'today_completed': today_completed,
        'today_pending': today_pending,
        'today_revenue': today_revenue,
        'today_tips': today_tips,
        'top_barber_today': top_today['barber__display_name'] if top_today else '—',
        'pending_approvals_count': pending_approvals_count,
    }
    return render(request, 'admin/dashboard.html', context)


@staff_required
def admin_calendar_view(request):
    context = {
        'user_role': getattr(request.user, 'profile', None) and request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'calendar',
    }
    return render(request, 'admin/calendar.html', context)


from apps.cashflow.models import PaymentMethod

@staff_required
def admin_bookings_view(request):
    payment_methods = PaymentMethod.objects.filter(is_active=True)
    context = {
        'user_role': getattr(request.user, 'profile', None) and request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'bookings',
        'payment_methods': payment_methods,
    }
    return render(request, 'admin/bookings.html', context)


@admin_required
def admin_barbers_view(request):
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'barbers',
    }
    return render(request, 'admin/barbers.html', context)


@staff_required
def admin_barber_agenda_view(request):
    """Vista personal del barbero — su propia agenda."""
    context = {
        'user_role': getattr(request.user, 'profile', None) and request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'my_agenda',
    }
    return render(request, 'admin/barber_agenda.html', context)


@admin_required
def admin_clients_view(request):
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'clients',
    }
    return render(request, 'admin/clients.html', context)


@admin_required
def admin_charts_view(request):
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'charts',
    }
    return render(request, 'admin/charts.html', context)


@role_required('superadmin', 'admin')
def admin_settings_view(request):
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'settings',
    }
    return render(request, 'admin/settings.html', context)


@staff_required
def admin_gallery_view(request):
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'gallery',
    }
    return render(request, 'admin/gallery.html', context)


@staff_required
def admin_reels_view(request):
    from apps.barbers.models import Barber
    barbers = Barber.objects.filter(is_available=True)
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'reels',
        'barbers': barbers,
    }
    return render(request, 'admin/reels.html', context)


from .decorators import operational_admin_required
from apps.cashflow.models import Sale, Expense, Commission, DailyClose
from django.db.models import Sum
from django.utils import timezone

@operational_admin_required
def admin_cashflow_view(request):
    today = timezone.localtime(timezone.now()).date()
    
    # Pendientes por cerrar
    pending_sales = Sale.objects.filter(included_in_daily_close__isnull=True)
    pending_expenses = Expense.objects.filter(included_in_daily_close__isnull=True)
    
    # Solo consideramos las ventas aprobadas para las finanzas y comisiones
    approved_sales = pending_sales.filter(approval_status=Sale.STATUS_APPROVED)
    
    # Pendientes de aprobación (para notificaciones de Frank)
    pending_approvals_count = pending_sales.filter(approval_status=Sale.STATUS_PENDING).count()

    # Totales parciales
    total_sales = approved_sales.aggregate(t=Sum('final_price'))['t'] or 0
    total_tips = approved_sales.aggregate(t=Sum('tip_amount'))['t'] or 0
    total_expenses = pending_expenses.aggregate(t=Sum('amount'))['t'] or 0
    
    # Comisiones parciales
    commissions = Commission.objects.filter(sale__in=approved_sales)
    total_commissions = commissions.aggregate(t=Sum('commission_amount'))['t'] or 0
    
    net_income = total_sales - total_commissions - total_expenses

    recent_closes = DailyClose.objects.all().order_by('-date', '-closed_at')[:10]

    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'cashflow',
        'today': today,
        'pending_sales_count': approved_sales.count(),
        'pending_approvals_count': pending_approvals_count,
        'total_sales': total_sales,
        'total_tips': total_tips,
        'total_expenses': total_expenses,
        'total_commissions': total_commissions,
        'net_income': net_income,
        'recent_closes': recent_closes,
    }
    return render(request, 'admin/cashflow.html', context)


@operational_admin_required
def admin_expenses_view(request):
    expenses = Expense.objects.all().order_by('-created_at')[:50]
    
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'expenses',
        'expenses': expenses,
    }
    return render(request, 'admin/expenses.html', context)


@operational_admin_required
def admin_inventory_view(request):
    from apps.inventory.models import InventoryItem
    items = InventoryItem.objects.all().order_by('category', 'name')
    
    # Calculate stats
    low_stock_count = sum(1 for item in items if item.is_low_stock)
    
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'inventory',
        'items': items,
        'low_stock_count': low_stock_count,
    }
    return render(request, 'admin/inventory.html', context)


from .decorators import superadmin_required

@superadmin_required
def admin_reports_view(request):
    from django.utils import timezone
    now = timezone.localtime(timezone.now())
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'reports',
        'current_year': now.year,
        'current_month': now.month,
    }
    return render(request, 'admin/reports.html', context)


@role_required('superadmin', 'admin')
def admin_audit_log_view(request):
    """Vista del Log de Auditoría. Solo accesible para superadmin y admin (batman).
    Frank (operational_admin) y barberos no tienen acceso."""
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'audit_log',
    }
    return render(request, 'admin/audit_log.html', context)


@superadmin_required
def admin_reviews_view(request):
    """Vista del panel de encuestas y calificaciones de clientes."""
    from apps.bookings.models import Review
    from apps.barbers.models import Barber
    from django.db.models import Avg, Count
    
    barbers = Barber.objects.filter(is_available=True).annotate(
        review_count=Count('bookings__review'),
        avg_rating=Avg('bookings__review__barber_rating')
    ).order_by('-avg_rating')
    
    reviews = Review.objects.select_related('booking__barber', 'booking__service').order_by('-created_at')[:50]
    
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'reviews',
        'barbers': barbers,
        'reviews': reviews,
    }
    return render(request, 'admin/reviews.html', context)
