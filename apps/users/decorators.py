"""Decorators for template-based views with role checks."""
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def role_required(*roles):
    """Decorator that checks if the logged-in user has one of the given roles."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('admin_login')
            profile = getattr(request.user, 'profile', None)
            if not profile or profile.role not in roles:
                from django.contrib.auth import logout
                logout(request)
                messages.error(request, 'No tienes permisos para acceder a esta sección.')
                return redirect('admin_login')
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def admin_required(view_func):
    """Shortcut: requires admin, operational_admin or superadmin role."""
    return role_required('admin', 'operational_admin', 'superadmin')(view_func)


def superadmin_required(view_func):
    """Shortcut: only superadmins (Camilo, Juan David)."""
    return role_required('superadmin')(view_func)


def operational_admin_required(view_func):
    """Shortcut: operational_admin (Frank) or superadmin."""
    return role_required('operational_admin', 'superadmin')(view_func)


def staff_required(view_func):
    """Shortcut: requires any staff role (barber, admin, operational_admin, superadmin)."""
    return role_required('barber', 'admin', 'operational_admin', 'superadmin')(view_func)


def permission_required(permission_name):
    """Decorator that checks a granular permission property on the user's profile."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('admin_login')
            profile = getattr(request.user, 'profile', None)
            if not profile or not getattr(profile, permission_name, False):
                messages.error(request, 'No tienes permisos para realizar esta acción.')
                return redirect('admin_dashboard')
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
