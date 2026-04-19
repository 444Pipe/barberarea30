"""Role-based permissions for DRF views."""
from rest_framework.permissions import BasePermission


class IsSuperAdmin(BasePermission):
    """Only super admins (Camilo, Juan David): precios, egresos fijos, auditoría."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        profile = getattr(request.user, 'profile', None)
        return profile and profile.is_superadmin


class IsOperationalAdminOrAbove(BasePermission):
    """Operational admin (Frank) or super admin: cierre de caja, propinas, ventas."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        profile = getattr(request.user, 'profile', None)
        return profile and profile.role in ('superadmin', 'operational_admin')


class IsAdminOrAbove(BasePermission):
    """Admin de barbería, operational admin, or super admin."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        profile = getattr(request.user, 'profile', None)
        return profile and profile.is_admin


class IsBarberOrAbove(BasePermission):
    """Any authenticated staff member (barber, admin, operational_admin, superadmin)."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        profile = getattr(request.user, 'profile', None)
        return profile is not None


class HasProfilePermission(BasePermission):
    """Checks a named permission property on UserProfile.
    Usage: set `required_permission = 'can_modify_prices'` on the view class.
    """
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        profile = getattr(request.user, 'profile', None)
        if not profile:
            return False
        perm = getattr(view, 'required_permission', None)
        if perm is None:
            return True
        return getattr(profile, perm, False)
