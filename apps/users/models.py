from django.db import models
from django.contrib.auth.models import User


class Barbershop(models.Model):
    """Barbería — escalable para soportar múltiples locales."""
    name = models.CharField(max_length=200, default='Área 30 Barber Club')
    address = models.CharField(max_length=300, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    whatsapp = models.CharField(max_length=20, blank=True)
    instagram = models.CharField(max_length=100, blank=True)
    tiktok = models.CharField(max_length=100, blank=True)
    opening_time = models.TimeField(default='09:00')
    closing_time = models.TimeField(default='20:00')
    sunday_opening = models.TimeField(default='09:00')
    sunday_closing = models.TimeField(default='14:00')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Barbería'
        verbose_name_plural = 'Barberías'

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    """Perfil de usuario con roles del sistema.

    Jerarquía de roles:
      superadmin       → Acceso total (Camilo, Juan David): precios, promociones, egresos fijos, auditoría.
      operational_admin → Líder de piso (Frank): agenda, propinas, ventas, inventario, cierre diario.
      admin            → Admin de barbería: gestión operativa estándar.
      barber           → Barbero: solo su agenda y descuentos pre-aprobados.
    """
    ROLES = [
        ('superadmin', 'Super Administrador'),
        ('operational_admin', 'Administrador Operativo'),
        ('admin', 'Admin de Barbería'),
        ('barber', 'Barbero'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=25, choices=ROLES, default='barber')
    barbershop = models.ForeignKey(
        Barbershop, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='staff'
    )
    phone = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    bio = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Perfil de Usuario'
        verbose_name_plural = 'Perfiles de Usuarios'

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username} ({self.get_role_display()})'

    @property
    def is_superadmin(self):
        return self.role == 'superadmin'

    @property
    def is_operational_admin(self):
        return self.role == 'operational_admin'

    @property
    def is_admin(self):
        """True para admin de barbería, operational_admin y superadmin."""
        return self.role in ('superadmin', 'operational_admin', 'admin')

    @property
    def is_admin_only(self):
        """True solo para admin de barbería estándar."""
        return self.role == 'admin'

    @property
    def is_barber(self):
        return self.role == 'barber'

    # ── Permisos granulares ────────────────────────────────────────
    @property
    def can_modify_prices(self):
        """Solo SuperAdministradores pueden modificar precios."""
        return self.role == 'superadmin'

    @property
    def can_manage_promotions(self):
        """Solo SuperAdministradores gestionan porcentajes de promociones."""
        return self.role == 'superadmin'

    @property
    def can_manage_fixed_expenses(self):
        """Solo SuperAdministradores gestionan egresos fijos (arriendo, servicios)."""
        return self.role == 'superadmin'

    @property
    def can_view_audit_log(self):
        """Solo SuperAdministradores pueden ver el registro de auditoría."""
        return self.role == 'superadmin'

    @property
    def can_confirm_sales(self):
        """Operational admin (Frank) y superiores pueden confirmar ventas."""
        return self.role in ('superadmin', 'operational_admin')

    @property
    def can_do_daily_close(self):
        """Operational admin (Frank) y superiores pueden hacer cierre de caja."""
        return self.role in ('superadmin', 'operational_admin')

    @property
    def can_manage_inventory(self):
        """Operational admin y superiores pueden gestionar inventario."""
        return self.role in ('superadmin', 'operational_admin', 'admin')

    @property
    def can_add_tips(self):
        """Operational admin y superiores pueden registrar propinas."""
        return self.role in ('superadmin', 'operational_admin')

    @property
    def can_modify_client_data(self):
        """Solo admin y superiores pueden modificar datos maestros de clientes."""
        return self.role in ('superadmin', 'admin')

    @property
    def can_manage_staff(self):
        """Solo SuperAdministradores pueden cambiar personal."""
        return self.role == 'superadmin'
