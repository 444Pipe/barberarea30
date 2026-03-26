"""Role-based permissions for DRF views."""
from rest_framework.permissions import BasePermission


class IsSuperAdmin(BasePermission):
    """Only super admins."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        profile = getattr(request.user, 'profile', None)
        return profile and profile.is_superadmin


class IsAdminOrAbove(BasePermission):
    """Admin de barbería or super admin."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        profile = getattr(request.user, 'profile', None)
        return profile and profile.is_admin


class IsBarberOrAbove(BasePermission):
    """Any authenticated staff member (barber, admin, superadmin)."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        profile = getattr(request.user, 'profile', None)
        return profile is not None
