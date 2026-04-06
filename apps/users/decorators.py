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
    """Shortcut: requires admin or superadmin role."""
    return role_required('admin', 'superadmin')(view_func)


def staff_required(view_func):
    """Shortcut: requires any staff role (barber, admin, superadmin)."""
    return role_required('barber', 'admin', 'superadmin')(view_func)
