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
    """Perfil de usuario con roles del sistema."""
    ROLES = [
        ('superadmin', 'Super Admin'),
        ('admin', 'Admin de Barbería'),
        ('barber', 'Barbero'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLES, default='barber')
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
    def is_admin(self):
        return self.role in ('superadmin', 'admin')

    @property
    def is_barber(self):
        return self.role == 'barber'
