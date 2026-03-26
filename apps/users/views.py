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
        username = request.POST.get('username', '').strip()
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
    """Dashboard principal — redirige barberos a su agenda."""
    profile = getattr(request.user, 'profile', None)
    context = {
        'user_role': profile.role if profile else 'unknown',
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'dashboard',
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


@staff_required
def admin_bookings_view(request):
    context = {
        'user_role': getattr(request.user, 'profile', None) and request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'bookings',
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


@admin_required
def admin_settings_view(request):
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'settings',
    }
    return render(request, 'admin/settings.html', context)
